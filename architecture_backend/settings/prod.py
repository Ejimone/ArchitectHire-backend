"""Production settings — hardened, DigitalOcean Spaces media, Sentry."""

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *

DEBUG = False

SECRET_KEY = env("SECRET_KEY")  # required — no default in production
ALLOWED_HOSTS = env("ALLOWED_HOSTS")  # required
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- Security hardening -----------------------------------------------------

SECURE_SSL_REDIRECT = True
# Platform health probes hit the container over plain HTTP with no forwarded
# proto; without this exemption every probe gets a 301 and the deploy is
# marked unhealthy.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# --- Media -------------------------------------------------------------------
# DigitalOcean Spaces when configured; droplet-local files otherwise (test-mode
# deploys without a Spaces bucket — Caddy serves /media from a shared volume).

if AWS_ACCESS_KEY_ID:
    STORAGES = {
        "default": {"BACKEND": "apps.core.storages.PublicMediaStorage"},
        "private": {"BACKEND": "apps.core.storages.PrivateMediaStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "private": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# --- Email ------------------------------------------------------------------

MAILERS["default"]["BACKEND"] = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

# --- Observability ----------------------------------------------------------

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# Structured JSON logs for aggregation (DO App Platform / Papertrail / Loki).
LOGGING["formatters"]["json"] = {
    "format": (
        '{{"level": "{levelname}", "time": "{asctime}", '
        '"logger": "{name}", "message": {message!r}}}'
    ),
    "style": "{",
}
LOGGING["handlers"]["console"]["formatter"] = "json"
LOGGING["root"]["level"] = "WARNING"
LOGGING["loggers"]["apps"]["level"] = "INFO"
