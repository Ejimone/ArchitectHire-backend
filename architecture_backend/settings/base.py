"""Base settings shared by all environments. Environment-specific values come from env vars."""

from pathlib import Path

import environ
from psycopg_pool import ConnectionPool

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
# How long writes accumulate before one purge is sent. A bulk publish saves hundreds of
# rows; this coalesces them into a single ping carrying the union of their tags.
REVALIDATE_DEBOUNCE_SECONDS = env.float("REVALIDATE_DEBOUNCE_SECONDS", default=0.5)

# --- Background work ---------------------------------------------------------
# Notifications and revalidation pings run on an in-process thread pool
# (apps/core/background.py) rather than Celery, because the deployment has no worker
# component and queued tasks were silently never executed.
# Eager = run inline in the calling thread; tests set this so assertions stay
# synchronous, matching what CELERY_TASK_ALWAYS_EAGER used to give them.
BACKGROUND_TASKS_EAGER = env.bool("BACKGROUND_TASKS_EAGER", default=False)
# Opt back in to Celery for notification fanout, but only where a worker really runs.
NOTIFY_VIA_CELERY = env.bool("NOTIFY_VIA_CELERY", default=False)

INSTALLED_APPS = [
    # Ordering here is load-bearing twice over, because TEMPLATES["DIRS"] is empty
    # and APP_DIRS=True makes template lookup follow this list:
    #   1. apps.studio first, so apps/studio/templates/admin/index.html shadows
    #      Unfold's — that override IS the Command Center dashboard.
    #   2. unfold before the admin config, so Unfold's remaining template overrides
    #      still beat django.contrib.admin's.
    "apps.studio",
    # BasicAppConfig (rather than plain "unfold") leaves admin.site alone so
    # StudioAdminConfig can install our own site below.
    "unfold.apps.BasicAppConfig",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.import_export",
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
    "apps.studio_api",
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
        # max_size is per *worker*, so the real ceiling is max_size × gunicorn workers,
        # and the cluster (db-s-1vcpu-1gb) allows 22 connections in total.
        #
        # These defaults have to track the worker count in the Dockerfile, and they had
        # fallen out of step with it: the defaults below were chosen for 2 workers
        # (8 × 2 = 16, fine) and the Dockerfile then went to 6 (8 × 6 = 48 against a cap
        # of 22). Nothing failed at rest, because min_size is what is held idle — it
        # failed under load, as "sorry, too many clients already", and it locked out
        # `manage.py migrate` and psql at exactly the moment someone needed them.
        #
        # 3 × 6 = 18 leaves 4 connections for migrations and the console, which is what
        # DEPLOY.md and the Dockerfile comment both already assumed. min_size 1 keeps
        # 6 idle connections across the fleet instead of 12.
        "OPTIONS": {
            "pool": {
                "min_size": env.int("DB_POOL_MIN", default=1),
                "max_size": env.int("DB_POOL_MAX", default=3),
                "timeout": 10,
                # Ping on checkout, and never keep one connection forever. Without the
                # check, a burst that kills the pool's connections (2026-08-15: a
                # 119-page prerender) leaves it handing out corpses — every request
                # then dies with PoolTimeout until someone restarts the app.
                "check": ConnectionPool.check_connection,
                "max_lifetime": 60 * 10,
            }
        },
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
        # Studio sign-in is a password endpoint on a staff-only surface. 10/hour was
        # strict enough that ten mistyped passwords locked the owner out of their own CMS
        # for an hour; 30 still caps credential stuffing at a rate that gets nowhere.
        "studio-login": "30/hour",
        # Authenticated editing. Deliberately generous: the studio issues ~4 calls per
        # canvas render and refreshes after every save, so the default `user` rate of
        # 120/min is reachable within minutes of normal work.
        "studio": "600/min",
    },
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# Largest file the Studio's upload endpoints accept. A modern phone photo is 3–8 MB and
# a DSLR JPEG 10–20 MB; anything above this is a mistake or an attack, and Caddy /
# the App Platform edge should reject it before Django ever buffers it.
STUDIO_MAX_UPLOAD_BYTES = env.int("STUDIO_MAX_UPLOAD_BYTES", default=30 * 1024 * 1024)

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

# --- django-solo ------------------------------------------------------------
# SOLO_CACHE is deliberately NOT set. Caching the singletons would save one query per
# composed page, but django-solo caches the instance object, and `DraftingConfig` and
# `EstimateConfig` declare float defaults on DecimalFields (`default=0.25`). A
# `get_or_create` that creates the row returns an instance holding those floats
# uncoerced; caching it makes that permanent, and `apps.orders.calculators._round50`
# then raises `AttributeError: 'float' object has no attribute 'quantize'` on every
# drafting quote. Fix the defaults to `Decimal("0.25")` first, then this is safe.

# --- CORS -------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
# The studio's browser-side calls (direct uploads with a ticket, search suggestions)
# tag themselves with the tab that made them, so the event the backend broadcasts about
# a write can be told apart from someone else's. A header the preflight does not admit
# fails the whole request, silently, in the browser.
from corsheaders.defaults import default_headers as _cors_default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*_cors_default_headers, "x-studio-client")
CORS_ALLOW_CREDENTIALS = True

# Origins permitted to open a WebSocket. Deliberately NOT ALLOWED_HOSTS-based:
# AllowedHostsOriginValidator compares the browser Origin (https://architecthire.com)
# against ALLOWED_HOSTS (the *.ondigitalocean.app service hostname), which would reject
# every legitimate handshake in production.
WS_ALLOWED_ORIGINS = env(
    "WS_ALLOWED_ORIGINS",
    # dict.fromkeys dedupes while keeping order — in dev FRONTEND_URL is already in
    # CORS_ALLOWED_ORIGINS, and a duplicated origin makes the validator's config
    # confusing to read in logs.
    default=",".join(dict.fromkeys([*CORS_ALLOWED_ORIGINS, FRONTEND_URL])),
).split(",")

# --- Scheduled jobs -----------------------------------------------------------
# There is no Celery beat process, so periodic work is driven by an external caller
# (Vercel Cron) hitting /api/v1/internal/cron/<job>/ with this shared secret.
# Blank disables the endpoint entirely.
CRON_SECRET = env("CRON_SECRET", default="")

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
# The bucket's own region. Wrong value = SigV4 signs for the wrong region and Spaces
# rejects every upload with SignatureDoesNotMatch, while unsigned reads keep working —
# so the failure shows up only as "saving an image in admin silently does nothing".
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="sfo3")
# Virtual-hosted, not path-style. With no custom domain, botocore's default against a
# custom `endpoint_url` is path-style, which emits
#   https://sfo3.digitaloceanspaces.com/<bucket>/media/...
# whose *hostname* is the shared regional endpoint. Next.js allowlists image hosts by
# hostname, so every such URL was rejected by /_next/image with a 400 and not one CMS
# image rendered on the site. Virtual-hosted puts the bucket in the hostname
#   https://<bucket>.sfo3.digitaloceanspaces.com/media/...
# which is the form both frontends already allow.
AWS_S3_ADDRESSING_STYLE = env("AWS_S3_ADDRESSING_STYLE", default="virtual")
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
            # Notification email goes out on a background thread that the pool must be
            # able to join at worker shutdown; an unbounded SMTP connect parks it
            # forever. (Belongs here, not in a top-level EMAIL_TIMEOUT — Django refuses
            # the deprecated setting once MAILERS is defined.)
            "TIMEOUT": env.int("EMAIL_TIMEOUT", default=10),
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
