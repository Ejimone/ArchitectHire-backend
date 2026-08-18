"""Production settings — hardened, object-storage or VM-disk media, Sentry."""

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
# Two supported shapes, chosen explicitly with MEDIA_BACKEND. Never a silent fallback:
# a FileSystemStorage that nothing serves accepts uploads and 404s every one of them, and
# on an ephemeral filesystem loses them at the next deploy — that failure was live once.
#
#   MEDIA_BACKEND=s3     Object storage (DigitalOcean Spaces or any S3-compatible bucket).
#                        Requires the four AWS_* values; refuses to boot without them.
#   MEDIA_BACKEND=local  The VM's disk. MEDIA_URL must be the *absolute* public URL Caddy
#                        serves MEDIA_ROOT at (https://api.architecthire.com/media/), so
#                        the frontends' image allowlists see a stable hostname. Private
#                        files live outside MEDIA_ROOT and are only reachable through
#                        signed, expiring URLs (apps.core.storages.SignedLocalStorage).
MEDIA_BACKEND = env("MEDIA_BACKEND", default="s3")

if MEDIA_BACKEND == "local":
    MEDIA_ROOT = env("MEDIA_ROOT", default="/app/media")
    MEDIA_URL = env("MEDIA_URL")  # required — absolute, with a trailing slash
    if not MEDIA_URL.startswith(("http://", "https://")) or not MEDIA_URL.endswith("/"):
        raise ImproperlyConfigured(
            "MEDIA_URL must be an absolute URL ending in '/' when MEDIA_BACKEND=local, e.g. "
            "https://api.architecthire.com/media/ — the frontends allowlist images by hostname."
        )
    PRIVATE_MEDIA_ROOT = env("PRIVATE_MEDIA_ROOT", default="/app/media-private")
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},
        },
        "private": {
            "BACKEND": "apps.core.storages.SignedLocalStorage",
            "OPTIONS": {"location": PRIVATE_MEDIA_ROOT},
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
elif MEDIA_BACKEND == "s3":
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
            "Object storage is required when MEDIA_BACKEND=s3; these are unset: "
            f"{', '.join(_missing_media_env)}. Without them Django would accept uploads and "
            "serve 404 for every one of them. Set them, or set MEDIA_BACKEND=local."
        )
    STORAGES = {
        "default": {"BACKEND": "apps.core.storages.PublicMediaStorage"},
        "private": {"BACKEND": "apps.core.storages.PrivateMediaStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    raise ImproperlyConfigured(f"MEDIA_BACKEND must be 's3' or 'local', not {MEDIA_BACKEND!r}.")

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
