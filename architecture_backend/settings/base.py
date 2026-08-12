"""Base settings shared by all environments. Environment-specific values come from env vars."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
)

# Local .env for development; in containers/production, real env vars win.
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
# Instant cache purge on the frontend after admin content edits (blank = disabled).
FRONTEND_REVALIDATE_URL = env("FRONTEND_REVALIDATE_URL", default="")
REVALIDATE_SECRET = env("REVALIDATE_SECRET", default="")

INSTALLED_APPS = [
    # Unfold powers the admin UI and must precede django.contrib.admin so its
    # template overrides win. BasicAppConfig (rather than plain "unfold") leaves
    # admin.site alone so StudioAdminConfig can install our own site below.
    "unfold.apps.BasicAppConfig",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.import_export",
    "apps.studio",
    # Replaces "django.contrib.admin"; installs apps.studio.sites.StudioAdminSite.
    "apps.studio.admin_apps.StudioAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "solo",
    "import_export",
    # Local
    "apps.core",
    "apps.accounts",
    "apps.cms",
    "apps.catalog",
    "apps.jurisdictions",
    "apps.projects",
    "apps.search",
    "apps.providers",
    "apps.orders",
    "apps.engagements",
    "apps.payments",
    "apps.messaging",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "architecture_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "architecture_backend.wsgi.application"
ASGI_APPLICATION = "architecture_backend.asgi.application"

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": {
        **env.db(
            "DATABASE_URL",
            default="postgres://architecthire:architecthire@localhost:5432/architecthire",
        ),
        # Native psycopg pool instead of per-thread persistent connections.
        # Under ASGI every request's ORM work runs on its own thread, so
        # CONN_MAX_AGE=60 held one Postgres connection per thread and a
        # parallel `next build` prerender (110+ routes) blew straight through
        # Postgres's 100-connection cap ("sorry, too many clients already").
        # Pooling requires CONN_MAX_AGE=0 (Django refuses the combination).
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"pool": {"min_size": 2, "max_size": 20, "timeout": 10}},
    }
}

AUTH_USER_MODEL = "accounts.User"

# --- Cache / Redis ----------------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379")

# Managed Redis/Valkey (DigitalOcean et al) speaks TLS via rediss://; Celery
# refuses a rediss:// broker unless ssl_cert_reqs is explicit, and the db
# number must come before the query string.
_REDIS_IS_TLS = REDIS_URL.startswith("rediss://")
_REDIS_QS = "?ssl_cert_reqs=required" if _REDIS_IS_TLS else ""


def _redis_db(number: int) -> str:
    return f"{REDIS_URL}/{number}{_REDIS_QS}"


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": _redis_db(0),
        "KEY_PREFIX": "ah",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [_redis_db(2)]},
    }
}

# --- Celery -----------------------------------------------------------------

CELERY_BROKER_URL = _redis_db(1)
CELERY_RESULT_BACKEND = _redis_db(1)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "apps.notifications.tasks.*": {"queue": "notifications"},
}
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240

# --- REST framework ---------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.ClerkAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "200/min",
        "user": "120/min",
        "contact": "5/hour",
        "newsletter": "5/hour",
        "estimates": "30/hour",
    },
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ArchitectHire API",
    "DESCRIPTION": "CMS-driven marketplace API for ArchitectHire.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

# --- Auth (Clerk) -----------------------------------------------------------

CLERK_SECRET_KEY = env("CLERK_SECRET_KEY", default="")
CLERK_PUBLISHABLE_KEY = env("CLERK_PUBLISHABLE_KEY", default="")
CLERK_JWKS_URL = env("CLERK_JWKS_URL", default="")
CLERK_ISSUER = env("CLERK_ISSUER", default="")
CLERK_WEBHOOK_SIGNING_SECRET = env("CLERK_WEBHOOK_SIGNING_SECRET", default="")
# Origins allowed as `azp` (authorized party) in Clerk session tokens.
CLERK_AUTHORIZED_PARTIES = [FRONTEND_URL]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- CORS -------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# --- I18N -------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static & media ---------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Admin UI (Studio) ------------------------------------------------------

# The design system lives in apps/studio/config.py so settings stays configuration
# and the palette stays next to the CSS that consumes it. Bound via attribute access
# rather than `from ... import UNFOLD`, which ruff's F401 strips as an unused import.
from apps.studio import config as _studio_config  # noqa: E402

UNFOLD = _studio_config.UNFOLD

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "private": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(BASE_DIR / "media" / "private")},
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# DigitalOcean Spaces (S3-compatible) — consumed by prod settings / storage classes.
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")
AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="nyc3")
AWS_DEFAULT_ACL = None
AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

# --- Email ------------------------------------------------------------------

MAILERS = {
    "default": {
        "BACKEND": env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"),
        "OPTIONS": {
            "HOST": env("EMAIL_HOST", default=""),
            "PORT": env.int("EMAIL_PORT", default=587),
            "USERNAME": env("EMAIL_HOST_USER", default=""),
            "PASSWORD": env("EMAIL_HOST_PASSWORD", default=""),
            "USE_TLS": True,
        },
    },
}
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="ArchitectHire <no-reply@architecthire.com>")

# --- Payments ---------------------------------------------------------------

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

# --- Web push ---------------------------------------------------------------

VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", default="")
VAPID_ADMIN_EMAIL = env("VAPID_ADMIN_EMAIL", default="")

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
        "apps": {"level": "INFO"},
    },
}
