"""Test settings — dev plus unthrottled API."""

from .dev import *

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "contact": "1000/hour",
        "newsletter": "1000/hour",
        "estimates": "10000/hour",
    },
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed

# In-memory channels + eager celery for tests
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Own cache namespace. The tests use a dedicated database but the same Redis, so
# without this a running dev server shares the content-version key and cached
# page payloads with the suite and makes cache assertions flaky.
CACHES = {"default": {**CACHES["default"], "KEY_PREFIX": "ah-test"}}

# Tests must never talk to real Stripe, regardless of what's in .env —
# get_gateway() selects the mock when no key is set.
STRIPE_SECRET_KEY = ""
FRONTEND_REVALIDATE_URL = ""  # tests must never ping a real frontend
STRIPE_WEBHOOK_SECRET = ""
