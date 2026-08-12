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
# Bake the static manifest into the image (whitenoise Manifest storage 500s
# without it). Dummy env — collectstatic never touches the DB or real secrets.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=build \
    python manage.py collectstatic --noinput
USER app
EXPOSE 8000
CMD ["gunicorn", "architecture_backend.asgi:application", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--workers", "4", \
     "--access-logfile", "-"]
