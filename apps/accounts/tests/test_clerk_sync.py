"""The profile backfill that keeps Clerk ids and pending addresses off screens."""

import io
import json
from unittest import mock

import pytest

from apps.accounts import clerk_sync
from apps.accounts.factories import UserFactory

PROFILE = {
    "id": "user_abc",
    "first_name": "Maya",
    "last_name": "Ellis",
    "image_url": "https://img.clerk.com/maya.png",
    "primary_email_address_id": "em_1",
    "email_addresses": [
        {"id": "em_1", "email_address": "maya@example.com"},
        {"id": "em_2", "email_address": "old@example.com"},
    ],
}


def _response(payload: dict):
    return io.BytesIO(json.dumps(payload).encode())


class TestFetchClerkProfile:
    def test_requires_secret_key(self, settings):
        settings.CLERK_SECRET_KEY = ""
        assert clerk_sync.fetch_clerk_profile("user_abc") is None

    def test_fetches_with_user_agent(self, settings):
        settings.CLERK_SECRET_KEY = "sk_test_x"
        opened = mock.MagicMock()
        opened.__enter__.return_value = _response(PROFILE)
        with mock.patch.object(
            clerk_sync.urllib.request, "urlopen", return_value=opened
        ) as urlopen:
            profile = clerk_sync.fetch_clerk_profile("user_abc")
        assert profile == PROFILE
        request = urlopen.call_args.args[0]
        # Clerk answers 403 without a User-Agent — regression guard.
        assert request.get_header("User-agent") == clerk_sync.USER_AGENT
        assert request.full_url.endswith("/users/user_abc")

    def test_api_failure_is_soft(self, settings):
        settings.CLERK_SECRET_KEY = "sk_test_x"
        with mock.patch.object(clerk_sync.urllib.request, "urlopen", side_effect=OSError("down")):
            assert clerk_sync.fetch_clerk_profile("user_abc") is None


@pytest.mark.django_db
class TestApplyClerkProfile:
    def test_fills_all_blanks(self):
        user = UserFactory(
            email="user_abc@pending.clerk.local",
            first_name="",
            last_name="",
            avatar_url="",
            clerk_id="user_abc",
        )
        changed = clerk_sync.apply_clerk_profile(user, PROFILE)
        user.refresh_from_db()
        assert set(changed) == {"email", "first_name", "last_name", "avatar_url"}
        assert user.email == "maya@example.com"
        assert user.display_name == "Maya Ellis"

    def test_never_steals_an_existing_email(self):
        UserFactory(email="maya@example.com")
        user = UserFactory(
            email="user_abc@pending.clerk.local", first_name="", last_name="", clerk_id="user_abc"
        )
        changed = clerk_sync.apply_clerk_profile(user, PROFILE)
        user.refresh_from_db()
        assert "email" not in changed
        assert user.has_placeholder_email

    def test_complete_row_is_untouched(self):
        user = UserFactory(
            email="real@example.com",
            first_name="Real",
            last_name="Name",
            avatar_url="https://img.example/x.png",
        )
        assert clerk_sync.apply_clerk_profile(user, PROFILE) == []


@pytest.mark.django_db
class TestBackfillUser:
    def test_noop_when_row_has_basics(self):
        user = UserFactory(email="real@example.com", first_name="Real")
        with mock.patch.object(clerk_sync, "fetch_clerk_profile") as fetch:
            assert clerk_sync.backfill_user(user) == []
        fetch.assert_not_called()

    def test_noop_when_profile_unavailable(self):
        user = UserFactory(email="user_abc@pending.clerk.local", first_name="", clerk_id="user_abc")
        with mock.patch.object(clerk_sync, "fetch_clerk_profile", return_value=None):
            assert clerk_sync.backfill_user(user) == []

    def test_backfills(self):
        user = UserFactory(
            email="user_abc@pending.clerk.local",
            first_name="",
            last_name="",
            avatar_url="",
            clerk_id="user_abc",
        )
        with mock.patch.object(clerk_sync, "fetch_clerk_profile", return_value=PROFILE):
            changed = clerk_sync.backfill_user(user)
        assert "email" in changed
        user.refresh_from_db()
        assert user.display_name == "Maya Ellis"
