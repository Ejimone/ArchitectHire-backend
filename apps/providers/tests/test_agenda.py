"""The provider agenda: scheduled calls and milestone deadlines in one pass."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.factories import UserFactory
from apps.engagements.models import Engagement, Milestone
from apps.jurisdictions.models import State
from apps.messaging.models import Message, Thread, ThreadParticipant
from apps.projects.models import Project

AGENDA = "/api/v1/providers/me/agenda/"


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions")


@pytest.fixture
def provider(seeded, db):
    return UserFactory(role="architect")


def schedule_call(provider, when, counterpart="Dana Whitmore", body="Video call scheduled"):
    first, last = counterpart.split(" ")
    other = UserFactory(first_name=first, last_name=last)
    thread = Thread.objects.create()
    ThreadParticipant.objects.create(thread=thread, user=provider)
    ThreadParticipant.objects.create(thread=thread, user=other)
    return Message.objects.create(
        thread=thread, sender=other, kind=Message.Kind.CALL, body=body, call_time=when
    )


def add_deadline(provider, title, due, status=Milestone.Status.UPCOMING, project="Addition"):
    client = UserFactory(role="client")
    engagement = Engagement.objects.create(
        project=Project.objects.create(
            owner=client,
            title=project,
            project_type="Residential",
            scope="Addition",
            sqft=2400,
            state=State.objects.get(code="CA"),
            architect=provider,
        ),
        client=client,
        provider=provider,
        kind=Engagement.Kind.HOURLY,
        hourly_rate=Decimal("135"),
    )
    return Milestone.objects.create(engagement=engagement, title=title, due_date=due, status=status)


@pytest.mark.django_db
class TestAgenda:
    def test_requires_auth(self, api_client):
        assert api_client.get(AGENDA).status_code == 401

    def test_calls_and_deadlines_merge_in_date_order(self, api_client, provider):
        now = timezone.now()
        schedule_call(provider, now + timedelta(days=9))
        add_deadline(provider, "Permit set", (now + timedelta(days=3)).date(), project="Cole ADU")

        api_client.force_authenticate(user=provider)
        body = api_client.get(AGENDA).json()

        assert [item["kind"] for item in body] == ["deadline", "call"]
        assert body[0]["title"] == "Permit set · Cole ADU"
        assert body[1]["title"] == "Video call scheduled · Dana Whitmore"

    def test_only_the_window_ahead_counts(self, api_client, provider):
        now = timezone.now()
        schedule_call(provider, now - timedelta(hours=2), counterpart="Past Call")
        schedule_call(provider, now + timedelta(days=40), counterpart="Far Future")
        add_deadline(provider, "Yesterday", (now - timedelta(days=1)).date())
        add_deadline(provider, "Next quarter", (now + timedelta(days=60)).date())
        keeper = schedule_call(provider, now + timedelta(days=2), counterpart="In Window")

        api_client.force_authenticate(user=provider)
        body = api_client.get(AGENDA).json()

        assert [item["title"] for item in body] == [f"{keeper.body} · In Window"]

    def test_every_thread_is_searched_not_just_the_busiest_few(self, api_client, provider):
        """The dashboard used to scan the six most recent threads, so a call booked
        in a quieter conversation never surfaced."""
        buried = schedule_call(
            provider, timezone.now() + timedelta(days=4), counterpart="Quiet Thread"
        )
        for index in range(8):
            thread = schedule_call(
                provider, timezone.now() + timedelta(days=10), counterpart=f"Chatty Person{index}"
            ).thread
            Message.objects.create(thread=thread, sender=provider, body="still talking")

        api_client.force_authenticate(user=provider)
        body = api_client.get(AGENDA).json()

        assert body[0]["date"] == buried.call_time.isoformat().replace("+00:00", "Z")
        assert body[0]["title"] == "Video call scheduled · Quiet Thread"

    def test_a_call_without_a_body_still_reads(self, api_client, provider):
        schedule_call(provider, timezone.now() + timedelta(days=1), body="")

        api_client.force_authenticate(user=provider)
        assert api_client.get(AGENDA).json()[0]["title"] == "Call · Dana Whitmore"

    def test_finished_milestones_are_not_deadlines(self, api_client, provider):
        due = (timezone.now() + timedelta(days=5)).date()
        add_deadline(provider, "Signed off", due, status=Milestone.Status.DONE)
        add_deadline(provider, "Still open", due, project="Ellis Loft")

        api_client.force_authenticate(user=provider)
        body = api_client.get(AGENDA).json()

        assert [item["title"] for item in body] == ["Still open · Ellis Loft"]
        assert body[0]["date"] == due.isoformat()

    def test_other_peoples_agendas_stay_theirs(self, api_client, provider):
        stranger = UserFactory(role="architect")
        schedule_call(stranger, timezone.now() + timedelta(days=2))
        add_deadline(stranger, "Not mine", (timezone.now() + timedelta(days=2)).date())

        api_client.force_authenticate(user=provider)
        assert api_client.get(AGENDA).json() == []

    @pytest.mark.parametrize(
        ("query", "expected"),
        [("", 1), ("?days=45", 2), ("?days=500", 2), ("?days=0", 0), ("?days=-5", 0)],
    )
    def test_days_is_clamped_to_a_sane_window(self, api_client, provider, query, expected):
        now = timezone.now()
        schedule_call(provider, now + timedelta(days=10), counterpart="Soon Enough")
        schedule_call(provider, now + timedelta(days=40), counterpart="Next Month")
        schedule_call(provider, now + timedelta(days=200), counterpart="Way Out")

        api_client.force_authenticate(user=provider)
        assert len(api_client.get(f"{AGENDA}{query}").json()) == expected

    def test_an_unreadable_days_falls_back_to_the_default(self, api_client, provider):
        schedule_call(provider, timezone.now() + timedelta(days=10))

        api_client.force_authenticate(user=provider)
        assert len(api_client.get(f"{AGENDA}?days=three-weeks").json()) == 1

    def test_the_whole_agenda_is_a_handful_of_queries(
        self, api_client, provider, django_assert_max_num_queries
    ):
        for index in range(6):
            schedule_call(
                provider,
                timezone.now() + timedelta(days=index + 1),
                counterpart=f"Client Number{index}",
            )
            add_deadline(
                provider, f"Milestone {index}", (timezone.now() + timedelta(days=2)).date()
            )

        api_client.force_authenticate(user=provider)
        with django_assert_max_num_queries(6):  # auth + calls (+participants) + deadlines
            assert len(api_client.get(AGENDA).json()) == 12
