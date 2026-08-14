"""Content-version cache keys: seeding, the double bump around commit, granularity.

Runs against an isolated in-memory cache: the counters are process-global in Redis, and
any other client touching content would make these assertions racy.

Everything here needs a database because the second bump rides on `on_commit`.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.core.cache import (
    CONTENT_EPOCH_KEY,
    bump_content_version,
    content_etag,
    get_content_epoch,
    get_content_version,
    page_cache_key,
    slugs_for_tags,
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


def slug_key(slug: str) -> str:
    return f"cms:v:{slug}"


class TestSeeding:
    def test_missing_keys_seed_at_one(self):
        assert get_content_version("landing") == (1, 1)
        assert cache.get(CONTENT_EPOCH_KEY) == 1
        assert cache.get(slug_key("landing")) == 1

    def test_a_slugless_read_returns_the_epoch_only(self):
        assert get_content_version() == (1, 0)


class TestGranularity:
    """The property the whole design exists for: an edit to one page must not make the
    other 112 pages rebuild, because a rebuild is 18 database round trips."""

    def test_a_page_edit_bumps_only_that_page(self):
        before_other = page_cache_key("about")
        before_nav = page_cache_key("_nav")

        bump_content_version({"cms:page:landing"})

        assert page_cache_key("landing") != page_cache_key("landing", (1, 1))
        assert page_cache_key("about") == before_other
        assert page_cache_key("_nav") == before_nav

    def test_chrome_tags_map_to_their_own_slugs(self):
        assert slugs_for_tags({"cms:nav"}) == {"_nav"}
        assert slugs_for_tags({"cms:footer"}) == {"_footer"}
        assert slugs_for_tags({"cms:catalog:plans"}) == {"_plans"}
        assert slugs_for_tags({"cms:page:city:oakland"}) == {"city:oakland"}

    def test_the_catch_all_widens_to_everything(self):
        assert slugs_for_tags({"cms"}) is None
        assert slugs_for_tags(()) is None

    def test_an_unmapped_tag_widens_rather_than_narrows(self):
        """Over-purging costs one rebuild; under-purging serves stale content until an
        unrelated write happens to clear it."""
        assert slugs_for_tags({"cms:something-new"}) is None
        assert slugs_for_tags({"cms:page:landing", "cms:something-new"}) is None

    def test_a_site_wide_write_moves_every_key(self):
        before = page_cache_key("about")
        bump_content_version({"cms"})  # e.g. site settings, which every page embeds
        assert page_cache_key("about") != before


class TestBumpTiming:
    def test_bump_increments_before_the_commit(self):
        """The signal fires inside the admin's transaction; waiting for the commit would
        leave a window where readers still serve — and refill — the old key."""
        cache.set(slug_key("landing"), 41, timeout=None)
        bump_content_version({"cms:page:landing"})  # this test's transaction is still open
        assert get_content_version("landing")[1] == 42

    def test_bump_increments_again_after_the_commit(self, django_capture_on_commit_callbacks):
        """The second bump orphans whatever a mid-transaction read cached under the first."""
        cache.set(slug_key("landing"), 41, timeout=None)
        with django_capture_on_commit_callbacks(execute=True):
            bump_content_version({"cms:page:landing"})
        assert get_content_version("landing")[1] == 43

    def test_epoch_bump_recovers_when_the_key_expired(self):
        bump_content_version()  # incr on a missing key raises ValueError
        assert get_content_epoch() == 2

    def test_slug_bump_recovers_when_the_key_expired(self):
        bump_content_version({"cms:page:landing"})
        assert get_content_version("landing")[1] == 2

    def test_the_purge_is_scheduled_only_once_the_write_is_visible(
        self, django_capture_on_commit_callbacks
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


class TestDerivedKeys:
    def test_keys_carry_both_counters(self):
        cache.set(CONTENT_EPOCH_KEY, 3, timeout=None)
        cache.set(slug_key("landing"), 7, timeout=None)
        assert page_cache_key("landing") == "page:landing:v3.7"
        assert content_etag("landing") == '"3.7-landing"'

    def test_a_pinned_version_beats_the_current_one(self):
        """How the page view keys its lookup and its store to one version, not two."""
        cache.set(CONTENT_EPOCH_KEY, 3, timeout=None)
        cache.set(slug_key("landing"), 7, timeout=None)
        assert page_cache_key("landing", (3, 5)) == "page:landing:v3.5"
        assert content_etag("landing", (3, 5)) == '"3.5-landing"'

    def test_a_lost_seed_race_returns_the_winner(self):
        """`cache.add` is a no-op when another writer got there first, so the seed path
        re-reads rather than assuming the value it tried to write."""
        cache.set(CONTENT_EPOCH_KEY, 9, timeout=None)
        assert get_content_epoch() == 9
