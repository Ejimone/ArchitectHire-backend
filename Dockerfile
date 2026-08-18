# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app

FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM base AS runtime
RUN groupadd -r app && useradd -r -g app -d /app app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
ENV PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=architecture_backend.settings.prod
# /app itself is root-owned; the app user needs these two writable.
RUN mkdir -p /app/staticfiles /app/media && chown app:app /app/staticfiles /app/media
USER app
# Bake the static manifest into the image (whitenoise Manifest storage 500s
# without it). Runs as the app user so a later runtime collectstatic can still
# rewrite these files. Dummy env — never touches the DB or real secrets.
# MEDIA_BACKEND=local with a placeholder URL keeps prod settings importable without
# object-storage credentials; collectstatic only touches the whitenoise staticfiles
# backend, never the media one. Real values come from the runtime environment.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=build \
    MEDIA_BACKEND=local MEDIA_URL=https://build-only.invalid/media/ \
    python manage.py collectstatic --noinput
EXPOSE 8000
# Worker count is memory-bound, not CPU-bound: each worker loads its own copy of
# Django + DRF + channels + celery + stripe and costs ~110MB resident. Measured
# anonymous memory under load on the 512MB App Platform instance:
#   4 workers -> 435MB (85% — this is what was pinning the box)
#   2 workers -> 230MB (45%)
# These are uvicorn ASGI workers — but Django runs every sync view on ONE
# shared thread per worker (asgiref thread_sensitive), so each worker really
# handles one HTTP request at a time; websockets are what the async loop
# buys us. Workers therefore *are* the concurrency limit for HTTP.
#
# WORKER COUNT IS A BUDGET DECISION HERE, not a performance one.
#
# This runs on apps-s-1vcpu-0.5gb -- 512MB, $5/mo, the budget for this project.
# All MEASURED on live DO metrics, 2026-08-17, not estimated:
#
#   4 workers / 1GB    85% at idle, restart loop   (this broke `next build`: 504)
#   2 workers / 1GB    ~424MB
#   2 workers / 512MB  OOM cycle: healthy ~100s, down ~80s, repeatedly
#   1 worker  / 512MB  203-226MB steady, 0 restarts, 450/450 requests OK  <-- this
#
# A loaded worker is ~122MB (Django + DRF + channels + celery + stripe + unfold +
# boto3 + Pillow), growing to ~350MB peak under heavy serialisation and falling
# back afterwards.
#
# Django serves every sync view on ONE shared thread per worker, so workers ARE
# the HTTP concurrency limit: this is one request at a time. Accepted knowingly --
# cached content responses are ~120ms, so one worker still serves ~8 req/s.
#
# Raising this REQUIRES raising the instance size first. It does not fit otherwise.
#
# NOTE: this CMD is only in force while the App Platform spec has no
# `run_command`. The spec used to set one pinning `--workers 2`, which silently
# overrode this line — so the app ran 2 workers no matter what the Dockerfile
# said. If concurrency ever looks wrong again, check the spec before this file.
# --max-requests, reversing an earlier decision, because the constraint changed.
#
# It was removed on the reasoning that recycling force-drops live WebSockets. True,
# and with one worker it drops all of them. But on a 512MB instance there is no
# "45% headroom to absorb heap growth" to trade against: MEASURED, a worker loads
# at ~122MB and grows to ~300MB serving requests, because CPython returns freed
# arenas to the OS only grudgingly. Without recycling that growth is one-way and
# ends in an OOM loop -- which is exactly what 512MB did (healthy ~100s, down ~80s).
#
# So: recycle, and let the frontend reconnect. lib/realtime/manager.ts already
# reconnects with exponential backoff and jitter and replays from its send queue,
# so a dropped socket is a blip rather than a lost session. Jitter keeps a future
# multi-worker deployment from recycling every worker at once.
# --graceful-timeout gives uvicorn time to send real close frames on shutdown, so
# clients see a clean close instead of an opaque 1006.
CMD ["gunicorn", "architecture_backend.asgi:application", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--workers", "1", \
     "--max-requests", "400", \
     "--max-requests-jitter", "100", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
