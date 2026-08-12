"""Notification fanout: in-app row, Web Push delivery and the email fallback."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pywebpush import WebPushException

from apps.accounts.factories import UserFactory
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.tasks import notify


@pytest.fixture
def vapid(settings):
    settings.VAPID_PRIVATE_KEY = "test-private-key"
    settings.VAPID_PUBLIC_KEY = "test-public-key"
    settings.VAPID_ADMIN_EMAIL = "ops@architecthire.com"


def subscribe(user, endpoint):
    return PushSubscription.objects.create(
        user=user, endpoint=endpoint, p256dh="p256dh-key", auth="auth-secret"
    )


@pytest.mark.django_db
class TestNotify:
    def test_unknown_user_is_a_no_op(self):
        assert notify(999999, "system", "Title") == "user-missing"

    def test_web_push_is_attempted_for_each_subscription(self, vapid):
        user = UserFactory()
        subscribe(user, "https://push.example.com/a")
        subscribe(user, "https://push.example.com/b")

        with patch("pywebpush.webpush") as webpush:
            result = notify(user.pk, "system", "Milestone approved", "Nice work")

        assert result == "delivered push=True"
        assert webpush.call_count == 2
        first = webpush.call_args_list[0].kwargs
        assert first["vapid_private_key"] == "test-private-key"
        assert first["vapid_claims"] == {"sub": "mailto:ops@architecthire.com"}
        assert Notification.objects.filter(user=user, title="Milestone approved").exists()

    @pytest.mark.parametrize("status_code", [404, 410])
    def test_stale_subscriptions_are_pruned(self, vapid, status_code):
        user = UserFactory()
        subscribe(user, f"https://push.example.com/gone-{status_code}")

        exception = WebPushException("gone", response=SimpleNamespace(status_code=status_code))
        with patch("pywebpush.webpush", side_effect=exception):
            result = notify(user.pk, "system", "Title")

        assert result == "delivered push=False"
        assert not PushSubscription.objects.filter(user=user).exists()

    def test_other_push_failures_keep_the_subscription(self, vapid):
        user = UserFactory()
        subscribe(user, "https://push.example.com/flaky")

        exception = WebPushException("boom", response=SimpleNamespace(status_code=500))
        with patch("pywebpush.webpush", side_effect=exception):
            result = notify(user.pk, "system", "Title")

        assert result == "delivered push=False"
        assert PushSubscription.objects.filter(user=user).exists()

    def test_email_is_the_fallback_when_push_is_unavailable(self, settings):
        settings.VAPID_PRIVATE_KEY = ""
        settings.VAPID_PUBLIC_KEY = ""
        user = UserFactory()
        with patch("django.core.mail.send_mail") as send_mail:
            assert notify(user.pk, "system", "Welcome", "Hello") == "delivered push=False"
        assert send_mail.call_args.kwargs["recipient_list"] == [user.email]

    def test_email_failures_never_break_the_caller(self, settings):
        settings.VAPID_PRIVATE_KEY = ""
        user = UserFactory()
        with patch("django.core.mail.send_mail", side_effect=OSError("smtp down")):
            assert notify(user.pk, "system", "Welcome") == "delivered push=False"

    def test_muted_kind_skips_delivery(self, vapid):
        user = UserFactory()
        user.notification_preferences.new_messages = False
        user.notification_preferences.save()
        subscribe(user, "https://push.example.com/muted")

        with patch("pywebpush.webpush") as webpush:
            assert notify(user.pk, "new_message", "Ping") == "muted"

        assert webpush.call_count == 0
        assert Notification.objects.filter(user=user, kind="new_message").exists()


@pytest.mark.django_db
class TestWsFanout:
    def test_notification_new_event_mirrors_the_rest_payload(self, settings):
        from unittest.mock import AsyncMock, MagicMock, patch

        settings.VAPID_PRIVATE_KEY = ""
        settings.VAPID_PUBLIC_KEY = ""
        user = UserFactory()

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("apps.notifications.tasks.get_channel_layer", return_value=layer):
            notify(
                user.pk,
                "milestone",
                "Schematic set submitted",
                "Ready for review",
                {"engagement_id": 7},
            )

        group, message = layer.group_send.call_args.args
        assert group == f"user_{user.pk}"
        event = message["event"]
        assert event["type"] == "notification.new"
        assert event["unread"] == 1
        row = event["notification"]
        assert row["kind"] == "milestone"
        assert row["title"] == "Schematic set submitted"
        assert row["data"] == {"engagement_id": 7}
        assert row["read_at"] is None
        # The in-app row itself was written before the event fired.
        assert Notification.objects.filter(user=user, kind="milestone").count() == 1

    def test_muted_kind_still_fans_out_in_app_event(self, settings):
        from unittest.mock import AsyncMock, MagicMock, patch

        settings.VAPID_PRIVATE_KEY = ""
        settings.VAPID_PUBLIC_KEY = ""
        user = UserFactory()
        user.notification_preferences.new_messages = False
        user.notification_preferences.save()

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("apps.notifications.tasks.get_channel_layer", return_value=layer):
            assert notify(user.pk, "new_message", "New message") == "muted"

        # Muting gates push/email only — the bell still updates live.
        assert layer.group_send.await_count == 1
