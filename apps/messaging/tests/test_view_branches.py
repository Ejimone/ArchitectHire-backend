"""Messaging model strings, serializer labels and the view error branches."""

import pytest
from django.contrib.admin.sites import site
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.jurisdictions.models import State
from apps.messaging.admin import MessageAdmin
from apps.messaging.models import Message, Thread, ThreadParticipant
from apps.messaging.serializers import ThreadSerializer
from apps.orders.models import Order
from apps.projects.models import Project


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions")


@pytest.fixture
def hired_project(seeded, db):
    client = UserFactory(role="client")
    architect = UserFactory(role="architect")
    project = Project.objects.create(
        owner=client,
        title="ADU · California",
        project_type="Residential",
        scope="ADU",
        sqft=640,
        state=State.objects.get(code="CA"),
        status="underway",
        architect=architect,
    )
    return client, architect, project


class TestStringsAndLabels:
    def test_thread_str_without_project_or_order(self):
        assert str(Thread(id=3)) == "Thread #3 · direct"

    def test_thread_without_a_project_is_never_contact_gated(self):
        assert Thread().contact_gated is False

    def test_message_str(self):
        message = Message(sender=UserFactory.build(email="dana@example.com"), body="Hello there")
        assert str(message) == "dana@example.com: Hello there"

    def test_context_label_falls_back_to_the_order_then_blank(self):
        serializer = ThreadSerializer()
        assert serializer.get_context_label(Thread(order=Order(kind="render"))) == (
            "3D visualization"
        )
        assert serializer.get_context_label(Thread()) == ""

    def test_admin_short_body_truncates(self):
        model_admin = MessageAdmin(Message, site)
        assert model_admin.short_body(Message(body="x" * 100)) == "x" * 60


@pytest.mark.django_db
class TestThreadCreation:
    def test_owner_can_open_a_thread_by_project(self, api_client, hired_project):
        client, architect, project = hired_project
        api_client.force_authenticate(user=client)
        response = api_client.post("/api/v1/threads/", {"project_id": project.pk}, format="json")
        assert response.status_code == 201
        assert response.json()["other_name"] == architect.get_full_name()

    def test_architect_can_open_a_thread_by_project(self, api_client, hired_project):
        client, architect, project = hired_project
        api_client.force_authenticate(user=architect)
        response = api_client.post("/api/v1/threads/", {"project_id": project.pk}, format="json")
        assert response.status_code == 201
        assert response.json()["other_name"] == client.get_full_name()

    def test_stranger_gets_404(self, api_client, hired_project):
        *_, project = hired_project
        api_client.force_authenticate(user=UserFactory())
        assert (
            api_client.post(
                "/api/v1/threads/", {"project_id": project.pk}, format="json"
            ).status_code
            == 404
        )

    def test_missing_identifier_is_a_400(self, api_client, hired_project):
        client, *_ = hired_project
        api_client.force_authenticate(user=client)
        response = api_client.post("/api/v1/threads/", {}, format="json")
        assert response.status_code == 400
        assert response.json()["detail"] == "Pass match_id or project_id."


@pytest.mark.django_db
class TestMessageBranches:
    @pytest.fixture
    def thread(self, hired_project):
        client, architect, project = hired_project
        thread = Thread.objects.create(project=project)
        ThreadParticipant.objects.create(thread=thread, user=client)
        ThreadParticipant.objects.create(thread=thread, user=architect)
        return client, architect, thread

    def test_history_is_readable(self, api_client, thread):
        client, _, thread_obj = thread
        Message.objects.create(thread=thread_obj, sender=client, body="First")
        api_client.force_authenticate(user=client)
        body = api_client.get(f"/api/v1/threads/{thread_obj.pk}/messages/").json()
        assert [m["body"] for m in body] == ["First"]

    def test_archived_thread_rejects_new_messages(self, api_client, thread):
        client, _, thread_obj = thread
        Thread.objects.filter(pk=thread_obj.pk).update(archived=True)
        api_client.force_authenticate(user=client)
        response = api_client.post(
            f"/api/v1/threads/{thread_obj.pk}/messages/", {"body": "Hi"}, format="json"
        )
        assert response.status_code == 409

    def test_empty_message_is_rejected(self, api_client, thread):
        client, _, thread_obj = thread
        api_client.force_authenticate(user=client)
        response = api_client.post(
            f"/api/v1/threads/{thread_obj.pk}/messages/", {"body": "   "}, format="json"
        )
        assert response.status_code == 400

    def test_read_receipt_on_a_foreign_thread_is_404(self, api_client, thread):
        client, *_ = thread
        api_client.force_authenticate(user=client)
        assert api_client.post("/api/v1/threads/999999/read/").status_code == 404

    def test_scheduling_a_call_needs_a_time(self, api_client, thread):
        client, _, thread_obj = thread
        api_client.force_authenticate(user=client)
        response = api_client.post(f"/api/v1/threads/{thread_obj.pk}/call/", {}, format="json")
        assert response.status_code == 400
        assert response.json()["detail"] == "call_time required."
