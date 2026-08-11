"""Notification model strings, targeted mark-read and push-subscription validation."""

import pytest

from apps.accounts.factories import UserFactory
from apps.accounts.models import User
from apps.notifications import vapid
from apps.notifications.models import Notification, PushSubscription


def test_notification_str():
    user = User(email="dana@example.com")
    notification = Notification(user=user, kind="milestone", title="Schematic approved")
    assert str(notification) == "milestone → dana@example.com: Schematic approved"


def test_push_subscription_str():
    subscription = PushSubscription(user=User(email="dana@example.com"))
    assert str(subscription) == "Push sub for dana@example.com"


def test_vapid_keypair_generator_prints_both_keys(capsys):
    vapid.generate()
    printed = capsys.readouterr().out.splitlines()
    assert printed[0].startswith("VAPID_PRIVATE_KEY=")
    assert printed[1].startswith("VAPID_PUBLIC_KEY=")


@pytest.mark.django_db
class TestNotificationEndpoints:
    def test_mark_read_can_target_specific_ids(self, api_client):
        user = UserFactory()
        first = Notification.objects.create(user=user, kind="system", title="One")
        Notification.objects.create(user=user, kind="system", title="Two")
        api_client.force_authenticate(user=user)

        response = api_client.post(
            "/api/v1/notifications/mark-read/", {"ids": [first.pk]}, format="json"
        )
        assert response.json() == {"marked": 1}
        assert api_client.get("/api/v1/notifications/").json()["unread"] == 1

    def test_push_subscription_requires_endpoint_and_keys(self, api_client):
        api_client.force_authenticate(user=UserFactory())
        response = api_client.post(
            "/api/v1/push-subscriptions/",
            {"endpoint": "https://push.example.com/x", "keys": {"p256dh": "only-one"}},
            format="json",
        )
        assert response.status_code == 400
        assert "keys.auth" in response.json()["detail"]
