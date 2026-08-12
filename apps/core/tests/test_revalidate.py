"""Frontend cache-purge pings: queued on content writes, debounced, fail-safe."""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.core.cache import bump_content_version
from apps.core.revalidate import DEBOUNCE_KEY, ping_frontend, schedule_ping
from apps.core.tasks import revalidate_frontend

PING = override_settings(
    FRONTEND_REVALIDATE_URL="http://frontend/api/revalidate", REVALIDATE_SECRET="s3cret"
)


@pytest.fixture(autouse=True)
def _fresh_debounce():
    cache.delete(DEBOUNCE_KEY)
    yield
    cache.delete(DEBOUNCE_KEY)


# --- The HTTP call -----------------------------------------------------------


def test_disabled_when_no_url_is_configured():
    assert ping_frontend() is False


@PING
def test_pings_the_frontend_with_the_shared_secret():
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert ping_frontend() is True
    request = urlopen.call_args.args[0]
    assert request.get_header("X-revalidate-secret") == "s3cret"
    assert request.get_method() == "POST"


@PING
def test_a_dead_frontend_never_breaks_a_save():
    with patch(
        "apps.core.revalidate.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        assert ping_frontend() is False


# --- Queueing ----------------------------------------------------------------


def test_scheduling_is_disabled_when_no_url_is_configured():
    assert schedule_ping() is False


@PING
def test_scheduling_queues_the_task_rather_than_calling_inline():
    """The whole point: the 3s HTTP call must not sit on the save's critical path."""
    with (
        patch("apps.core.tasks.revalidate_frontend.delay") as delay,
        patch("apps.core.revalidate.urllib.request.urlopen") as urlopen,
    ):
        assert schedule_ping() is True

    delay.assert_called_once_with()
    urlopen.assert_not_called()


@PING
def test_bursts_are_debounced_into_a_single_task():
    """A bulk publish saves hundreds of rows; it must enqueue one ping, not hundreds."""
    with patch("apps.core.tasks.revalidate_frontend.delay") as delay:
        assert schedule_ping() is True
        assert schedule_ping() is False  # within the debounce window
        assert schedule_ping() is False
    assert delay.call_count == 1


@PING
def test_falls_back_to_an_inline_ping_when_the_broker_is_down():
    with (
        patch("apps.core.tasks.revalidate_frontend.delay", side_effect=OSError("no broker")),
        patch("apps.core.revalidate.urllib.request.urlopen") as urlopen,
    ):
        urlopen.return_value = MagicMock()
        assert schedule_ping() is True

    urlopen.assert_called_once()


# --- Wiring ------------------------------------------------------------------


def test_content_version_bump_schedules_a_ping():
    with patch("apps.core.revalidate.schedule_ping") as schedule:
        bump_content_version()
    schedule.assert_called_once_with()


@PING
def test_the_task_performs_the_ping():
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert revalidate_frontend() is True
    urlopen.assert_called_once()
