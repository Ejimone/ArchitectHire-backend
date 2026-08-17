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
# The AWS_* values are dummies for the same reason SECRET_KEY is: prod settings now
# refuse to start without object storage (a silent FileSystemStorage fallback served 404
# for every uploaded image on this platform), and collectstatic only touches the
# whitenoise staticfiles backend, never the Spaces one. Real credentials come from the
# app spec at runtime.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=build \
    AWS_ACCESS_KEY_ID=build-only AWS_SECRET_ACCESS_KEY=build-only \
    AWS_STORAGE_BUCKET_NAME=build-only \
    AWS_S3_ENDPOINT_URL=https://build-only.invalid \
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
# 4 workers (~440MB) on the 1GB instance: double the concurrency of the 2 this
# deployment was actually running, with real headroom left rather than the 65%
# occupancy 6 would take. DB_POOL_MAX defaults to 3 (settings/base.py), so
# 4 x 3 = 12 sits well inside the Postgres cluster's 22-connection cap and
# leaves room for migrations and the console.
#
# NOTE: this CMD is only in force while the App Platform spec has no
# `run_command`. The spec used to set one pinning `--workers 2`, which silently
# overrode this line — so the app ran 2 workers no matter what the Dockerfile
# said. If concurrency ever looks wrong again, check the spec before this file.
# Deliberately no --max-requests: gunicorn's counter only sees HTTP requests, but
# these workers also hold every live WebSocket, so a recycle force-drops half the
# connected users, each of whom reconnects and triggers a full router.refresh().
# That amplification costs far more than the speculative heap growth the recycling
# guarded against, which the 45% headroom above already absorbs.
# --graceful-timeout gives uvicorn time to send real close frames on shutdown, so
# clients see a clean close instead of an opaque 1006.
CMD ["gunicorn", "architecture_backend.asgi:application", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--workers", "4", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
