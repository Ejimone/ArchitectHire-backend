from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.engagements.models import Engagement
from apps.jurisdictions.models import State
from apps.projects.models import Project


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog")


@pytest.fixture
def hired_project(seeded, db):
    from apps.providers.models import ArchitectProfile

    client = UserFactory(role="client")
    architect_user = UserFactory(role="architect")
    ArchitectProfile.objects.create(
        user=architect_user, onboarding_status="approved", hourly_rate=Decimal("135")
    )
    project = Project.objects.create(
        owner=client,
        title="Addition · California",
        project_type="Residential",
        scope="Addition",
        sqft=2400,
        state=State.objects.get(code="CA"),
        status="underway",
        architect=architect_user,
    )
    from apps.projects.models import Estimate

    estimate = Estimate.objects.create(
        user=client,
        project_type="Residential",
        scope="Addition",
        sqft=2400,
        state=project.state,
        timeline="Standard (10–12 wks)",
        addons={},
        rate=Decimal("5.31"),
        base=Decimal("12750"),
        addon_total=Decimal("4200"),
        multiplier=Decimal("1.337"),
        total=Decimal("21400"),
        low=Decimal("19688"),
        high=Decimal("23112"),
    )
    project.estimate = estimate
    project.save(update_fields=["estimate"])
    return project


def create_engagement(api_client, project, kind="dynamic_fixed_quote"):
    api_client.force_authenticate(user=project.owner)
    response = api_client.post(
        "/api/v1/engagements/", {"project_id": project.pk, "kind": kind}, format="json"
    )
    assert response.status_code == 201, response.content
    return response.json()


@pytest.mark.django_db
class TestEngagementCreation:
    def test_fixed_quote_snapshot(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project)
        assert body["total"] == "21400.00"
        assert body["fee_percent"] == "10.00"
        assert body["deposit_amount"] == "5350.00"  # 25% of 21,400 (design figure)
        assert body["platform_fee"] == "2140.00"  # 10% flat (locked decision)
        assert body["status"] == "contracted"

    def test_hourly_initial_escrow(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project, kind="hourly")
        assert body["hourly_rate"] == "135.00"
        assert body["deposit_amount"] == "2700.00"  # 135 × 20 hrs (design figure)

    def test_requires_hired_architect(self, api_client, seeded):
        client = UserFactory(role="client")
        project = Project.objects.create(
            owner=client,
            title="No architect yet",
            project_type="Residential",
            scope="ADU",
            sqft=640,
            state=State.objects.get(code="CA"),
        )
        api_client.force_authenticate(user=client)
        response = api_client.post(
            "/api/v1/engagements/", {"project_id": project.pk, "kind": "hourly"}, format="json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestMilestones:
    def _engagement(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project)
        return Engagement.objects.get(pk=body["id"])

    def test_milestones_must_sum_to_total(self, api_client, hired_project):
        engagement = self._engagement(api_client, hired_project)
        api_client.force_authenticate(user=engagement.provider)
        bad = [
            {"title": "Kickoff", "amount": "1000.00"},
            {"title": "Schematic design", "amount": "2000.00"},
        ]
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/milestones/", bad, format="json"
        )
        assert response.status_code == 400
        assert "sum" in response.json()["detail"]

        good = [
            {"title": "Kickoff", "amount": "0.00"},
            {"title": "Schematic design", "amount": "5350.00"},
            {"title": "Design development", "amount": "7490.00"},
            {"title": "Permit set & stamp", "amount": "8560.00"},
        ]
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/milestones/", good, format="json"
        )
        assert response.status_code == 201
        assert len(response.json()) == 4

    def test_state_machine_and_roles(self, api_client, hired_project):
        engagement = self._engagement(api_client, hired_project)
        api_client.force_authenticate(user=engagement.provider)
        api_client.post(
            f"/api/v1/engagements/{engagement.pk}/milestones/",
            [{"title": "Everything", "amount": "21400.00"}],
            format="json",
        )
        milestone_id = engagement.milestones.first().pk

        # Client cannot submit; provider can
        api_client.force_authenticate(user=engagement.client)
        assert api_client.post(f"/api/v1/milestones/{milestone_id}/submit/").status_code == 403
        api_client.force_authenticate(user=engagement.provider)
        assert (
            api_client.post(f"/api/v1/milestones/{milestone_id}/submit/").json()["status"]
            == "in_review"
        )

        # Provider cannot approve; client requests changes with chips + note
        assert api_client.post(f"/api/v1/milestones/{milestone_id}/approve/").status_code == 403
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/milestones/{milestone_id}/request-changes/",
            {"categories": ["Adjust the floor plan"], "note": "Kitchen wall"},
            format="json",
        )
        assert response.json()["status"] == "revising"

        # Provider resubmits; client approves; approval is terminal
        api_client.force_authenticate(user=engagement.provider)
        api_client.post(f"/api/v1/milestones/{milestone_id}/submit/")
        api_client.force_authenticate(user=engagement.client)
        assert (
            api_client.post(f"/api/v1/milestones/{milestone_id}/approve/").json()["status"]
            == "done"
        )
        api_client.force_authenticate(user=engagement.provider)
        assert api_client.post(f"/api/v1/milestones/{milestone_id}/submit/").status_code == 409

    def test_stranger_cannot_see_engagement(self, api_client, hired_project):
        engagement = self._engagement(api_client, hired_project)
        api_client.force_authenticate(user=UserFactory())
        assert api_client.get(f"/api/v1/engagements/{engagement.pk}/").status_code == 404


@pytest.mark.django_db
class TestRequotes:
    def test_requote_flow(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project)
        engagement = Engagement.objects.get(pk=body["id"])

        api_client.force_authenticate(user=engagement.provider)
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/requotes/",
            {"new_total": "24800.00", "reason": "Hidden structural complexity in the attic"},
            format="json",
        )
        assert response.status_code == 201
        requote_id = response.json()["id"]

        api_client.force_authenticate(user=engagement.client)
        approved = api_client.post(f"/api/v1/requotes/{requote_id}/approve/").json()
        assert approved["status"] == "approved"
        engagement.refresh_from_db()
        assert engagement.total == Decimal("24800.00")
        # Already resolved
        assert api_client.post(f"/api/v1/requotes/{requote_id}/decline/").status_code == 409


@pytest.mark.django_db
class TestTimeAndDeliverables:
    def test_time_entries_provider_writes_client_reads(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project, kind="hourly")
        engagement = Engagement.objects.get(pk=body["id"])

        api_client.force_authenticate(user=engagement.client)
        assert (
            api_client.post(
                f"/api/v1/engagements/{engagement.pk}/time-entries/",
                {"date": "2026-08-10", "hours": "3.5", "description": "Site measure"},
                format="json",
            ).status_code
            == 403
        )
        api_client.force_authenticate(user=engagement.provider)
        assert (
            api_client.post(
                f"/api/v1/engagements/{engagement.pk}/time-entries/",
                {"date": "2026-08-10", "hours": "3.5", "description": "Site measure"},
                format="json",
            ).status_code
            == 201
        )
        api_client.force_authenticate(user=engagement.client)
        body = api_client.get(f"/api/v1/engagements/{engagement.pk}/time-entries/").json()
        assert body["total_hours"] == "3.50"

    def test_deliverable_upload(self, api_client, hired_project):
        body = create_engagement(api_client, hired_project)
        engagement = Engagement.objects.get(pk=body["id"])
        api_client.force_authenticate(user=engagement.provider)
        upload = SimpleUploadedFile("A-201 Proposed plan.pdf", b"%PDF-1.4 test", "application/pdf")
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/deliverables/",
            {"file": upload, "name": "A-201 Proposed plan.pdf", "stamped": True},
            format="multipart",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["stamped"] is True
        assert body["is_new"] is True
        assert body["size_bytes"] > 0
