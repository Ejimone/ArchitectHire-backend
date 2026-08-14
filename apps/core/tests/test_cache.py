"""Content-version cache key: seeding, the double bump around commit, derived keys.

Runs against an isolated in-memory cache: the version key is process-global in
Redis, and any other client touching content would make these assertions racy.

Everything here needs a database because the second bump rides on `on_commit`.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.core.cache import (
    CONTENT_VERSION_KEY,
    bump_content_version,
    content_etag,
    get_content_version,
    page_cache_key,
)

pytestmark = pytest.mark.django_db


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


def test_bump_increments_before_the_commit():
    """The signal fires inside the admin's transaction; waiting for the commit would
    leave a window where readers still serve — and refill — the old key."""
    cache.set(CONTENT_VERSION_KEY, 41, timeout=None)
    bump_content_version()  # this test's own transaction is still open
    assert get_content_version() == 42


def test_bump_increments_again_after_the_commit(django_capture_on_commit_callbacks):
    """The second bump orphans whatever a mid-transaction read cached under the first."""
    cache.set(CONTENT_VERSION_KEY, 41, timeout=None)
    with django_capture_on_commit_callbacks(execute=True):
        bump_content_version()
    assert get_content_version() == 43


def test_bump_recovers_when_the_key_expired():
    bump_content_version()  # incr on a missing key raises ValueError
    assert get_content_version() == 2


def test_the_purge_is_scheduled_only_once_the_write_is_visible(
    django_capture_on_commit_callbacks,
):
    """Pinging pre-commit tells the frontend to rebuild from a snapshot without the
    edit in it — the stale page comes straight back."""
    with (
        patch("apps.core.revalidate.schedule_ping") as schedule,
        django_capture_on_commit_callbacks(execute=True) as callbacks,
    ):
        bump_content_version({"cms:nav"})
        schedule.assert_not_called()

    assert len(callbacks) == 1
    schedule.assert_called_once_with({"cms:nav"})


def test_derived_keys_carry_the_version():
    cache.set(CONTENT_VERSION_KEY, 7, timeout=None)
    assert page_cache_key("landing") == "page:landing:v7"
    assert content_etag("landing") == '"7-landing"'


def test_a_pinned_version_beats_the_current_one():
    """How the page view keys its lookup and its store to one version, not two."""
    cache.set(CONTENT_VERSION_KEY, 7, timeout=None)
    assert page_cache_key("landing", 5) == "page:landing:v5"
