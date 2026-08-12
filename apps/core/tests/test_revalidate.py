"""Frontend cache-purge pings: fired on content writes, debounced, fail-safe."""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.core.cache import bump_content_version
from apps.core.revalidate import DEBOUNCE_KEY, ping_frontend

PING = override_settings(
    FRONTEND_REVALIDATE_URL="http://frontend/api/revalidate", REVALIDATE_SECRET="s3cret"
)


@pytest.fixture(autouse=True)
def _fresh_debounce():
    cache.delete(DEBOUNCE_KEY)
    yield
    cache.delete(DEBOUNCE_KEY)


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
def test_bursts_are_debounced():
    with patch("apps.core.revalidate.urllib.request.urlopen") as urlopen:
        urlopen.return_value = MagicMock()
        assert ping_frontend() is True
        assert ping_frontend() is False  # within the debounce window
    assert urlopen.call_count == 1


@PING
def test_a_dead_frontend_never_breaks_a_save():
    with patch(
        "apps.core.revalidate.urllib.request.urlopen",
        side_effect=urllib.error.URLError("down"),
    ):
        assert ping_frontend() is False


def test_content_version_bump_triggers_a_ping():
    with patch("apps.core.revalidate.ping_frontend") as ping:
        bump_content_version()
    ping.assert_called_once_with()
