import base64
import hashlib
import hmac
import json
import time

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.factories import UserFactory

User = get_user_model()

SECRET_BYTES = b"0123456789abcdef0123456789abcdef"
TEST_SECRET = "whsec_" + base64.b64encode(SECRET_BYTES).decode()
WEBHOOK_URL = "/api/webhooks/clerk/"


def _signed_headers(payload: bytes, msg_id: str = "msg_1") -> dict:
    timestamp = str(int(time.time()))
    to_sign = f"{msg_id}.{timestamp}.{payload.decode()}".encode()
    signature = base64.b64encode(hmac.new(SECRET_BYTES, to_sign, hashlib.sha256).digest()).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{signature}",
    }


def _post_event(client, event: dict):
    payload = json.dumps(event).encode()
    return client.post(
        WEBHOOK_URL,
        data=payload,
        content_type="application/json",
        headers=_signed_headers(payload),
    )


@pytest.fixture(autouse=True)
def _webhook_secret(settings):
    settings.CLERK_WEBHOOK_SIGNING_SECRET = TEST_SECRET


@pytest.mark.django_db
class TestClerkWebhook:
    def test_rejects_bad_signature(self, client):
        payload = json.dumps({"type": "user.created", "data": {}}).encode()
        headers = _signed_headers(payload)
        headers["svix-signature"] = "v1,invalid"
        response = client.post(
            WEBHOOK_URL, data=payload, content_type="application/json", headers=headers
        )
        assert response.status_code == 400

    def test_user_created(self, client):
        event = {
            "type": "user.created",
            "data": {
                "id": "user_abc123",
                "primary_email_address_id": "em_1",
                "email_addresses": [{"id": "em_1", "email_address": "maya@example.com"}],
                "first_name": "Maya",
                "last_name": "Ellison",
                "image_url": "https://img.clerk.com/maya.png",
            },
        }
        response = _post_event(client, event)
        assert response.status_code == 204
        user = User.objects.get(clerk_id="user_abc123")
        assert user.email == "maya@example.com"
        assert user.first_name == "Maya"
        assert user.avatar_url == "https://img.clerk.com/maya.png"
        assert user.notification_preferences is not None

    def test_user_updated_by_clerk_id(self, client):
        UserFactory(email="old@example.com", clerk_id="user_upd1")
        event = {
            "type": "user.updated",
            "data": {
                "id": "user_upd1",
                "primary_email_address_id": "em_1",
                "email_addresses": [{"id": "em_1", "email_address": "new@example.com"}],
                "first_name": "New",
                "last_name": "Name",
                "image_url": "",
            },
        }
        assert _post_event(client, event).status_code == 204
        user = User.objects.get(clerk_id="user_upd1")
        assert user.email == "new@example.com"
        assert user.first_name == "New"

    def test_links_jit_provisioned_user_by_email(self, client):
        existing = UserFactory(email="jit@example.com", clerk_id=None)
        event = {
            "type": "user.created",
            "data": {
                "id": "user_jit9",
                "primary_email_address_id": "em_1",
                "email_addresses": [{"id": "em_1", "email_address": "jit@example.com"}],
                "first_name": "Jit",
                "last_name": "User",
                "image_url": "",
            },
        }
        assert _post_event(client, event).status_code == 204
        existing.refresh_from_db()
        assert existing.clerk_id == "user_jit9"
        assert User.objects.filter(email="jit@example.com").count() == 1

    def test_user_deleted_deactivates(self, client):
        UserFactory(clerk_id="user_gone")
        event = {"type": "user.deleted", "data": {"id": "user_gone", "deleted": True}}
        assert _post_event(client, event).status_code == 204
        assert User.objects.get(clerk_id="user_gone").is_active is False

    def test_unconfigured_secret_returns_503(self, client, settings):
        settings.CLERK_WEBHOOK_SIGNING_SECRET = ""
        response = client.post(WEBHOOK_URL, data=b"{}", content_type="application/json")
        assert response.status_code == 503

    def test_falls_back_to_the_first_email_when_no_primary_matches(self, client):
        event = {
            "type": "user.created",
            "data": {
                "id": "user_nofallbackid",
                "primary_email_address_id": "em_missing",
                "email_addresses": [{"id": "em_1", "email_address": "first@example.com"}],
                "first_name": "First",
                "last_name": "Email",
                "image_url": "",
            },
        }
        assert _post_event(client, event).status_code == 204
        assert User.objects.get(clerk_id="user_nofallbackid").email == "first@example.com"

    def test_event_without_a_clerk_id_is_ignored(self, client):
        before = User.objects.count()
        event = {"type": "user.created", "data": {"email_addresses": []}}
        assert _post_event(client, event).status_code == 204
        assert User.objects.count() == before

    def test_new_user_without_an_email_is_skipped(self, client):
        event = {"type": "user.created", "data": {"id": "user_noemail", "email_addresses": []}}
        assert _post_event(client, event).status_code == 204
        assert not User.objects.filter(clerk_id="user_noemail").exists()
