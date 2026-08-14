"""Frontend cache purges: what gets sent, when, and what happens when it fails.

The debounce is trailing-edge, so these assertions are about *accumulation*: a burst
of writes must produce one HTTP call carrying the union of everything that changed.
The leading-edge version this replaces could only ever promise the first writer's tags.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.admin.sites import site
from django.core.cache import cache
from django.db.models.signals import post_save
from django.test import override_settings
from django_redis import get_redis_connection

from apps.cms.admin import FAQAdmin
from apps.cms.models import FAQ, SiteSettings
from apps.cms.views import PageContentView
from apps.core.cache import bump_content_version, get_content_version, page_cache_key
from apps.core.revalidate import (
    CLAIM_KEY,
    MAX_TAGS,
    PENDING_TAGS_KEY,
    _flush_after_debounce,
    _key,
    ping_frontend,
    schedule_ping,
)
from apps.core.tasks import revalidate_frontend
from apps.payments.models import EscrowTransaction, SubscriptionPlan

PING = override_settings(
    FRONTEND_REVALIDATE_URL="http://frontend/api/revalidate",
    REVALIDATE_SECRET="s3cret",
    REVALIDATE_DEBOUNCE_SECONDS=0,  # in tests the trailing edge is now
)


@pytest.fixture(autouse=True)
def _fresh_pending():
    _drop_keys()
    yield
    _drop_keys()


def _drop_keys():
    get_redis_connection("default").delete(_key(PENDING_TAGS_KEY), _key(CLAIM_KEY))


def _pending():
    members = get_redis_connection("default").smembers(_key(PENDING_TAGS_KEY))
    return {tag.decode() for tag in members}


def _sent_tags(urlopen, call=0):
    return json.loads(urlopen.call_args_list[call].args[0].data)["tags"]


# --- The HTTP call -----------------------------------------------------------


def test_disabled_when_no_url_is_configured():
    assert ping_frontend() is False


@PING
def test_posts_the_tag_list_with_the_shared_secret():
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert ping_frontend(["cms:page:landing", "cms:nav"]) is True

    request = urlopen.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.get_header("X-revalidate-secret") == "s3cret"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"tags": ["cms:nav", "cms:page:landing"]}


@PING
def test_a_ping_with_no_tags_purges_everything():
    """The frontend attaches the catch-all to every fetch, so this is the big hammer."""
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert ping_frontend() is True
    assert _sent_tags(urlopen) == ["cms"]


@PING
def test_a_successful_ping_says_how_much_it_purged(caplog):
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        ping_frontend(["cms:nav", "cms:footer"])
    assert "Revalidated 2 frontend tag(s)" in caplog.text


@PING
def test_a_dead_frontend_is_logged_and_never_breaks_a_save(caplog):
    with patch(
        "apps.core.revalidate.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        assert ping_frontend(["cms"]) is False
    assert "revalidation ping failed" in caplog.text


@PING
def test_a_rejected_ping_is_logged_with_its_status_and_body(caplog):
    """HTTPError subclasses URLError: catching only the parent swallowed every 401 and
    500, so a wrong shared secret purged nothing, forever, in silence."""
    refused = urllib.error.HTTPError(
        "http://frontend/api/revalidate", 401, "Unauthorized", {}, io.BytesIO(b"bad secret")
    )
    with patch("apps.core.revalidate.urllib.request.urlopen", side_effect=refused):
        assert ping_frontend(["cms"]) is False

    assert "401" in caplog.text
    assert "bad secret" in caplog.text
    assert caplog.records[-1].levelname == "ERROR"


# --- Accumulating a burst ----------------------------------------------------


def test_scheduling_is_disabled_when_no_url_is_configured():
    assert schedule_ping() is False


@PING
def test_a_write_with_no_tags_pends_the_catch_all():
    with patch("apps.core.revalidate.run_in_background"):
        assert schedule_ping() is True
    assert _pending() == {"cms"}


@PING
@override_settings(REVALIDATE_DEBOUNCE_SECONDS=30)  # a window wide enough to lose in
def test_the_first_writer_schedules_the_flush_and_the_rest_ride_along():
    with patch("apps.core.revalidate.run_in_background") as run_in_background:
        assert schedule_ping({"cms:page:landing"}) is True
        assert schedule_ping({"cms:page:about"}) is False
        assert schedule_ping({"cms:nav"}) is False

    run_in_background.assert_called_once()
    assert _pending() == {"cms:page:landing", "cms:page:about", "cms:nav"}


@PING
def test_a_burst_becomes_one_ping_carrying_every_tag():
    """Studio's publish-everything button: hundreds of saves, one HTTP call, and no
    page left stale because a neighbour won the debounce."""
    with patch("apps.core.revalidate.run_in_background"):
        for scope in ("landing", "about", "careers"):
            schedule_ping({f"cms:page:{scope}"})

    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert _flush_after_debounce() is True

    assert urlopen.call_count == 1
    assert _sent_tags(urlopen) == ["cms:page:about", "cms:page:careers", "cms:page:landing"]
    assert _pending() == set()


@PING
def test_a_flush_with_nothing_pending_sends_nothing():
    """The price of preferring a duplicate flush to a lost one."""
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        assert _flush_after_debounce() is False
    urlopen.assert_not_called()


@PING
def test_a_purge_wider_than_the_cap_collapses_to_the_catch_all():
    with patch("apps.core.revalidate.run_in_background"):
        schedule_ping({f"cms:page:city:{n}" for n in range(MAX_TAGS + 1)})

    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert _flush_after_debounce() is True

    assert _sent_tags(urlopen) == ["cms"]
    # The remainder is dropped, not left to leak into the next flush.
    assert _pending() == set()


@PING
@override_settings(REVALIDATE_DEBOUNCE_SECONDS=30)
def test_the_flush_waits_out_the_window_then_releases_its_claim():
    with patch("apps.core.revalidate.run_in_background"):
        assert schedule_ping({"cms:nav"}) is True
        assert schedule_ping({"cms:footer"}) is False  # the 30s claim is still held

    with (
        patch("apps.core.revalidate.time.sleep") as sleep,
        patch("apps.core.revalidate.urllib.request.urlopen") as urlopen,
    ):
        urlopen.return_value = MagicMock()
        assert _flush_after_debounce() is True

    sleep.assert_called_once_with(30.0)
    assert _sent_tags(urlopen) == ["cms:footer", "cms:nav"]
    with patch("apps.core.revalidate.run_in_background"):
        assert schedule_ping({"cms:blog"}) is True  # the claim went with the flush


# --- The optional Celery route -----------------------------------------------


@PING
def test_the_task_delegates_to_the_ping():
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert revalidate_frontend(["cms:blog"]) is True
        assert revalidate_frontend() is True

    assert _sent_tags(urlopen, 0) == ["cms:blog"]
    assert _sent_tags(urlopen, 1) == ["cms"]


# --- Signal wiring -----------------------------------------------------------


@pytest.mark.django_db
def test_a_content_write_purges_the_page_it_changed():
    with patch("apps.core.signals.bump_content_version") as bump:
        FAQ.objects.create(scope="landing", question="QA-Tagged?", answer="A")
    bump.assert_called_once_with({"cms:page:landing"})


@pytest.mark.django_db
def test_loading_fixtures_purges_nothing():
    """`raw` means loaddata, replaying content that is already live."""
    with patch("apps.core.signals.bump_content_version") as bump:
        post_save.send(
            sender=FAQ,
            instance=FAQ(scope="landing", question="QA-Raw?", answer="A"),
            created=True,
            raw=True,
        )
    bump.assert_not_called()


@pytest.mark.django_db
def test_the_pricing_page_is_purged_when_a_plan_changes():
    """payments is the app the duplicated signal wiring forgot."""
    with patch("apps.core.signals.bump_content_version") as bump:
        SubscriptionPlan.objects.create(key="qa-practice", name="Practice", price_monthly=299)
    bump.assert_called_once_with({"cms:plans"})


def test_money_movement_is_not_content():
    """Escrow rows are written on every order; wiring them would purge all day long."""
    with patch("apps.core.signals.bump_content_version") as bump:
        post_save.send(sender=EscrowTransaction, instance=EscrowTransaction(), created=True)
    bump.assert_not_called()


@pytest.mark.django_db
def test_unpublishing_in_bulk_purges_the_pages_it_emptied():
    """`queryset.update()` emits no post_save, so the action purges by hand."""
    hidden = FAQ.objects.create(scope="services", question="QA-Bulk?", answer="A")
    also = FAQ.objects.create(scope="about", question="QA-Bulk-two?", answer="B")
    queryset = FAQ.objects.filter(pk__in=[hidden.pk, also.pk])

    with patch("apps.cms.admin.bump_content_version") as bump:
        FAQAdmin(FAQ, site).unpublish_selected(None, queryset)

    bump.assert_called_once_with({"cms:page:services", "cms:page:about"})
    assert FAQ.objects.filter(pk=hidden.pk, status="draft").exists()


# --- The composed-page cache-set guard ---------------------------------------

PAGE_URL = "/api/v1/content/pages/landing/"


@pytest.fixture
def isolated_cache(settings):
    """The content version is process-global in Redis, so a dev server or a second
    test run bumping it would make the before/after comparison below racy."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "page-cache-guard-tests",
        }
    }
    cache.clear()


@pytest.mark.django_db
def test_a_payload_built_across_a_version_bump_is_served_but_not_stored(api_client, isolated_cache):
    """Our snapshot may predate the write that bumped, and storing it would serve the
    pre-write page for the full TTL — the exact staleness the bump exists to end."""
    SiteSettings.get_solo()  # the composer creates this on demand; do it up front
    bump_content_version()  # force the next request to rebuild
    version = get_content_version()

    compose = PageContentView.build_payload

    def bump_midway(self, request, **kwargs):
        payload = compose(self, request, **kwargs)
        bump_content_version()  # a write commits while the page is being composed
        return payload

    with patch.object(PageContentView, "build_payload", bump_midway):
        assert api_client.get(PAGE_URL).status_code == 200

    assert cache.get(page_cache_key("landing", version)) is None


@pytest.mark.django_db
def test_an_uncontended_build_is_stored(api_client, isolated_cache):
    SiteSettings.get_solo()
    bump_content_version()
    version = get_content_version()

    assert api_client.get(PAGE_URL).status_code == 200
    assert cache.get(page_cache_key("landing", version)) is not None
