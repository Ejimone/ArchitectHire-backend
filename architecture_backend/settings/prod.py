"""Production settings — hardened, DigitalOcean Spaces media, Sentry."""

import sentry_sdk
from django.core.exceptions import ImproperlyConfigured
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
# DigitalOcean Spaces, and only Spaces.
#
# There used to be a FileSystemStorage fallback here for "test-mode deploys without a
# bucket", justified by a droplet where Caddy served /media from a shared volume. On App
# Platform — the deployment we actually run — that fallback is worse than useless:
# `urls.py` mounts MEDIA_URL only when DEBUG, and whitenoise is never given
# WHITENOISE_ROOT, so *every* media URL 404s. Worse, the container filesystem is
# ephemeral, so each upload also vanished on the next deploy. It failed silently: the
# admin reported a successful save and the site showed a broken image.
#
# So: refuse to boot instead. A missing credential is a deployment mistake, and a
# container that will not start is a mistake you find in 30 seconds rather than in a
# demo. The droplet runbook in DEPLOY.md sets these too.
_missing_media_env = [
    name
    for name, value in (
        ("AWS_ACCESS_KEY_ID", AWS_ACCESS_KEY_ID),
        ("AWS_SECRET_ACCESS_KEY", AWS_SECRET_ACCESS_KEY),
        ("AWS_STORAGE_BUCKET_NAME", AWS_STORAGE_BUCKET_NAME),
        ("AWS_S3_ENDPOINT_URL", AWS_S3_ENDPOINT_URL),
    )
    if not value
]
if _missing_media_env:
    raise ImproperlyConfigured(
        "Object storage is required in production; these are unset: "
        f"{', '.join(_missing_media_env)}. Without them Django would accept uploads and "
        "serve 404 for every one of them. Set them in the App Platform app spec."
    )

STORAGES = {
    "default": {"BACKEND": "apps.core.storages.PublicMediaStorage"},
    "private": {"BACKEND": "apps.core.storages.PrivateMediaStorage"},
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
