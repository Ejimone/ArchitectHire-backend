import pytest
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.jurisdictions.models import State
from apps.notifications.models import Notification
from apps.projects.models import Project


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions")


@pytest.fixture
def matched_pair(seeded, db):
    """Client + architect on a project still in 'choosing_architect' (contact gated)."""
    client = UserFactory(role="client", first_name="Dana", last_name="Kim")
    architect = UserFactory(role="architect", first_name="Maya", last_name="Ellison")
    project = Project.objects.create(
        owner=client,
        title="ADU · California",
        project_type="Residential",
        scope="ADU",
        sqft=640,
        state=State.objects.get(code="CA"),
    )
    from apps.projects.models import Match

    match = Match.objects.create(project=project, architect=architect, score=92)
    return client, architect, project, match


def make_thread(api_client, user, match):
    api_client.force_authenticate(user=user)
    response = api_client.post("/api/v1/threads/", {"match_id": match.pk}, format="json")
    assert response.status_code == 201
    return response.json()


@pytest.mark.django_db
class TestThreads:
    def test_create_from_match_get_or_create(self, api_client, matched_pair):
        client, architect, project, match = matched_pair
        first = make_thread(api_client, client, match)
        second = make_thread(api_client, client, match)
        assert first["id"] == second["id"]
        assert first["other_name"] == "Maya Ellison"
        assert first["contact_gated"] is True

    def test_stranger_cannot_create(self, api_client, matched_pair):
        *_, match = matched_pair
        api_client.force_authenticate(user=UserFactory())
        assert (
            api_client.post("/api/v1/threads/", {"match_id": match.pk}, format="json").status_code
            == 404
        )


@pytest.mark.django_db
class TestMessages:
    def test_send_receive_and_unread(self, api_client, matched_pair):
        client, architect, project, match = matched_pair
        thread = make_thread(api_client, client, match)

        api_client.post(
            f"/api/v1/threads/{thread['id']}/messages/",
            {"body": "Hi Maya — can we talk about the setback?"},
            format="json",
        )

        api_client.force_authenticate(user=architect)
        inbox = api_client.get("/api/v1/threads/").json()
        assert inbox[0]["unread_count"] == 1
        assert inbox[0]["last_message"]["body"].startswith("Hi Maya")

        api_client.post(f"/api/v1/threads/{thread['id']}/read/")
        inbox = api_client.get("/api/v1/threads/").json()
        assert inbox[0]["unread_count"] == 0

    def test_contact_details_redacted_until_hire(self, api_client, matched_pair):
        client, architect, project, match = matched_pair
        thread = make_thread(api_client, client, match)
        response = api_client.post(
            f"/api/v1/threads/{thread['id']}/messages/",
            {"body": "Email me at dana@example.com or call 415-555-0134"},
            format="json",
        )
        body = response.json()["body"]
        assert "dana@example.com" not in body
        assert "415-555-0134" not in body
        assert "[hidden until you hire]" in body

        # After hire, details flow freely
        project.status = "underway"
        project.architect = architect
        project.save()
        response = api_client.post(
            f"/api/v1/threads/{thread['id']}/messages/",
            {"body": "Email me at dana@example.com"},
            format="json",
        )
        assert "dana@example.com" in response.json()["body"]

    def test_message_creates_notification(
        self, api_client, matched_pair, django_capture_on_commit_callbacks
    ):
        client, architect, project, match = matched_pair
        thread = make_thread(api_client, client, match)
        with django_capture_on_commit_callbacks(execute=True):
            api_client.post(
                f"/api/v1/threads/{thread['id']}/messages/", {"body": "Ping"}, format="json"
            )
        notification = Notification.objects.filter(user=architect, kind="new_message").first()
        assert notification is not None
        assert notification.data["thread_id"] == thread["id"]

    def test_muted_preference_still_writes_in_app_row(
        self, api_client, matched_pair, django_capture_on_commit_callbacks
    ):
        client, architect, project, match = matched_pair
        architect.notification_preferences.new_messages = False
        architect.notification_preferences.save()
        thread = make_thread(api_client, client, match)
        with django_capture_on_commit_callbacks(execute=True):
            api_client.post(
                f"/api/v1/threads/{thread['id']}/messages/", {"body": "Quiet ping"}, format="json"
            )
        assert Notification.objects.filter(user=architect, kind="new_message").exists()

    def test_schedule_call(self, api_client, matched_pair):
        client, _, _, match = matched_pair
        thread = make_thread(api_client, client, match)
        response = api_client.post(
            f"/api/v1/threads/{thread['id']}/call/",
            {"call_time": "2026-08-14T10:00:00Z"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["kind"] == "call"


@pytest.mark.django_db
class TestNotificationsAPI:
    def test_list_and_mark_read(self, api_client):
        user = UserFactory()
        Notification.objects.create(user=user, kind="system", title="Welcome")
        api_client.force_authenticate(user=user)
        body = api_client.get("/api/v1/notifications/").json()
        assert body["unread"] == 1
        api_client.post("/api/v1/notifications/mark-read/", {}, format="json")
        assert api_client.get("/api/v1/notifications/").json()["unread"] == 0

    def test_push_subscription_roundtrip(self, api_client):
        user = UserFactory()
        api_client.force_authenticate(user=user)
        response = api_client.post(
            "/api/v1/push-subscriptions/",
            {
                "endpoint": "https://push.example.com/sub/abc",
                "keys": {"p256dh": "key", "auth": "secret"},
            },
            format="json",
        )
        assert response.status_code == 201
        response = api_client.delete(
            "/api/v1/push-subscriptions/",
            {"endpoint": "https://push.example.com/sub/abc"},
            format="json",
        )
        assert response.status_code == 200


@pytest.mark.django_db
class TestFanout:
    def test_ws_fanout_overrides_is_mine_and_echoes_sender(
        self, api_client, matched_pair, django_capture_on_commit_callbacks
    ):
        from unittest.mock import AsyncMock, MagicMock, patch

        client, architect, project, match = matched_pair
        thread = make_thread(api_client, client, match)

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch("apps.messaging.views.get_channel_layer", return_value=layer):
            with django_capture_on_commit_callbacks(execute=True):
                response = api_client.post(
                    f"/api/v1/threads/{thread['id']}/messages/",
                    {"body": "Kickoff call tomorrow?"},
                    format="json",
                )
        assert response.status_code == 201

        sent = {}
        for call in layer.group_send.call_args_list:
            group, event = call.args
            sent[group] = event["event"]["message"]["is_mine"]
        # Sender's own group gets an echo flagged mine; the counterpart's copy
        # is re-flagged, not reused from the sender-context serialization.
        assert sent == {f"user_{client.pk}": True, f"user_{architect.pk}": False}
