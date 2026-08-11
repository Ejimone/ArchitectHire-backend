"""Content-version cache key: seeding, bumping and the derived keys/ETags.

Runs against an isolated in-memory cache: the version key is process-global in
Redis, and any other client touching content would make these assertions racy.
"""

import pytest
from django.core.cache import cache

from apps.core.cache import (
    CONTENT_VERSION_KEY,
    bump_content_version,
    content_etag,
    get_content_version,
    page_cache_key,
)


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "content-version-tests",
        }
    }
    cache.clear()


def test_missing_key_seeds_version_one():
    assert get_content_version() == 1
    assert cache.get(CONTENT_VERSION_KEY) == 1


def test_bump_increments_an_existing_version():
    cache.set(CONTENT_VERSION_KEY, 41, timeout=None)
    bump_content_version()
    assert get_content_version() == 42


def test_bump_recovers_when_the_key_expired():
    bump_content_version()  # incr on a missing key raises ValueError
    assert get_content_version() == 2


def test_derived_keys_carry_the_version():
    cache.set(CONTENT_VERSION_KEY, 7, timeout=None)
    assert page_cache_key("landing") == "page:landing:v7"
    assert content_etag("landing") == '"7-landing"'
