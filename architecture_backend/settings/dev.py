"""Development settings — permissive defaults, console email, local media."""

from .base import *

DEBUG = env.bool("DEBUG", default=True)

ALLOWED_HOSTS = env(
    "ALLOWED_HOSTS",
    # host.docker.internal: the frontend Docker image build prerenders against
    # the host machine's backend.
    default=["localhost", "127.0.0.1", "0.0.0.0", "web", "host.docker.internal"],
)

if not CORS_ALLOWED_ORIGINS:
    # 3000 = the site, 3001 = the studio. The studio's canvas fetches search
    # suggestions from the browser, and its direct upload + WebSocket paths carry a
    # signed ticket in the browser — all of them are cross-origin from the studio.
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

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
