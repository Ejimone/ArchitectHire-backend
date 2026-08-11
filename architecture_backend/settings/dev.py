"""Development settings — permissive defaults, console email, local media."""

from .base import *

DEBUG = env.bool("DEBUG", default=True)

ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0", "web"])

if not CORS_ALLOWED_ORIGINS:
    CORS_ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Plain static storage in dev (no manifest hashing).
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Effectively no rate limiting locally. The Next.js dev server refetches content
# on every render and pre-renders 52 jurisdiction pages, which trips the
# production anon/estimate throttles within seconds and fails pages with 429s.
# The scopes must stay defined — views that declare `throttle_scope` raise
# ImproperlyConfigured if their rate is missing — so raise them instead of
# clearing them. Real rates apply in prod (see base.py).
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": dict.fromkeys(REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "100000/day"),
}
