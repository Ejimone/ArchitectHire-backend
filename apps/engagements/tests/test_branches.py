"""Engagement model validation, serializer guards and view error branches."""

import sys
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.engagements.models import Deliverable, Engagement, Milestone
from apps.engagements.serializers import ChangeRequestSerializer
from apps.jurisdictions.models import State
from apps.projects.models import Estimate, Project


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


@pytest.fixture
def engagement(api_client, hired_project):
    api_client.force_authenticate(user=hired_project.owner)
    response = api_client.post(
        "/api/v1/engagements/",
        {"project_id": hired_project.pk, "kind": "dynamic_fixed_quote"},
        format="json",
    )
    assert response.status_code == 201, response.content
    return Engagement.objects.get(pk=response.json()["id"])


class TestModelStrings:
    def test_engagement_str(self):
        contract = Engagement(
            project=Project(title="Addition · California"), kind="dynamic_fixed_quote"
        )
        assert str(contract) == "Addition · California · Fixed price"

    def test_milestone_str(self):
        assert str(Milestone(title="Schematic", amount=Decimal("5350.00"))) == (
            "Schematic ($5350.00)"
        )
        assert str(Milestone(title="Kickoff")) == "Kickoff ($0)"

    def test_deliverable_str(self):
        assert str(Deliverable(name="A-201 Proposed plan.pdf")) == "A-201 Proposed plan.pdf"


class TestEngagementValidation:
    def test_fixed_quote_requires_a_total(self):
        with pytest.raises(DjangoValidationError, match="need a total"):
            Engagement(kind=Engagement.Kind.FIXED).clean()

    def test_hourly_requires_a_rate(self):
        with pytest.raises(DjangoValidationError, match="need a rate"):
            Engagement(kind=Engagement.Kind.HOURLY).clean()

    def test_valid_contracts_pass_clean(self):
        Engagement(kind=Engagement.Kind.FIXED, total=Decimal("21400")).clean()
        Engagement(kind=Engagement.Kind.HOURLY, hourly_rate=Decimal("135")).clean()

    def test_hourly_milestones_are_not_summed(self):
        # No DB access: hourly returns before touching the milestone set.
        assert Engagement(kind=Engagement.Kind.HOURLY).validate_milestones_sum() is None


class TestSerializerGuards:
    def test_unknown_change_request_categories_are_rejected(self):
        serializer = ChangeRequestSerializer(data={"categories": ["Repaint the roof"], "note": ""})
        assert not serializer.is_valid()
        assert "Unknown categories" in str(serializer.errors["categories"][0])


@pytest.mark.django_db
class TestEngagementCreationGuards:
    def test_unknown_project_is_rejected(self, api_client, seeded):
        api_client.force_authenticate(user=UserFactory(role="client"))
        response = api_client.post(
            "/api/v1/engagements/", {"project_id": 999999, "kind": "hourly"}, format="json"
        )
        assert response.status_code == 400
        assert "Unknown project" in str(response.json())

    def test_a_project_can_only_have_one_engagement(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            "/api/v1/engagements/",
            {"project_id": engagement.project_id, "kind": "hourly"},
            format="json",
        )
        assert response.status_code == 400
        assert "already exists" in str(response.json())

    def test_fixed_quote_without_an_estimate_is_rejected(self, api_client, hired_project):
        hired_project.estimate = None
        hired_project.save(update_fields=["estimate"])
        api_client.force_authenticate(user=hired_project.owner)
        response = api_client.post(
            "/api/v1/engagements/",
            {"project_id": hired_project.pk, "kind": "dynamic_fixed_quote"},
            format="json",
        )
        assert response.status_code == 400
        assert "No estimate" in str(response.json())

    def test_hourly_without_a_configured_rate_is_rejected(self, api_client, hired_project):
        from apps.providers.models import ArchitectProfile

        ArchitectProfile.objects.filter(user=hired_project.architect).update(hourly_rate=None)
        api_client.force_authenticate(user=hired_project.owner)
        response = api_client.post(
            "/api/v1/engagements/",
            {"project_id": hired_project.pk, "kind": "hourly"},
            format="json",
        )
        assert response.status_code == 400
        assert "hourly rate" in str(response.json())

    def test_fee_falls_back_when_the_payments_app_is_unavailable(
        self, api_client, hired_project, monkeypatch
    ):
        """No FeePolicy import still honors the locked 0%-fee business model."""
        monkeypatch.setitem(sys.modules, "apps.payments.models", None)
        api_client.force_authenticate(user=hired_project.owner)
        response = api_client.post(
            "/api/v1/engagements/",
            {"project_id": hired_project.pk, "kind": "dynamic_fixed_quote"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["fee_percent"] == "0.00"


@pytest.mark.django_db
class TestEngagementReads:
    def test_list_returns_my_engagements(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        body = api_client.get("/api/v1/engagements/").json()
        assert [row["id"] for row in body["results"]] == [engagement.pk]

    def test_milestones_are_readable_by_both_parties(self, api_client, engagement):
        Milestone.objects.create(engagement=engagement, title="Kickoff", amount=Decimal("21400.00"))
        api_client.force_authenticate(user=engagement.client)
        body = api_client.get(f"/api/v1/engagements/{engagement.pk}/milestones/").json()
        assert [m["title"] for m in body] == ["Kickoff"]

    def test_requotes_are_readable(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        assert api_client.get(f"/api/v1/engagements/{engagement.pk}/requotes/").json() == []

    def test_deliverables_are_readable(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        assert api_client.get(f"/api/v1/engagements/{engagement.pk}/deliverables/").json() == []


@pytest.mark.django_db
class TestRoleGuards:
    def test_only_the_provider_defines_milestones(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/milestones/",
            [{"title": "Kickoff", "amount": "21400.00"}],
            format="json",
        )
        assert response.status_code == 403

    def test_a_single_milestone_object_is_accepted(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.provider)
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/milestones/",
            {"title": "Everything", "amount": "21400.00"},
            format="json",
        )
        assert response.status_code == 201
        assert len(response.json()) == 1

    def test_only_the_provider_raises_requotes(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/requotes/",
            {"new_total": "24800.00", "reason": "Scope grew"},
            format="json",
        )
        assert response.status_code == 403

    def test_only_the_provider_uploads_deliverables(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/deliverables/", {}, format="multipart"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestMilestoneActionGuards:
    @pytest.fixture
    def milestone(self, engagement):
        return Milestone.objects.create(
            engagement=engagement, title="Everything", amount=Decimal("21400.00")
        )

    def test_stranger_gets_404(self, api_client, milestone):
        api_client.force_authenticate(user=UserFactory())
        assert api_client.post(f"/api/v1/milestones/{milestone.pk}/submit/").status_code == 404

    def test_unknown_action_is_404(self, api_client, milestone, engagement):
        api_client.force_authenticate(user=engagement.client)
        assert api_client.post(f"/api/v1/milestones/{milestone.pk}/nudge/").status_code == 404

    def test_provider_cannot_request_changes(self, api_client, milestone, engagement):
        api_client.force_authenticate(user=engagement.provider)
        api_client.post(f"/api/v1/milestones/{milestone.pk}/submit/")
        response = api_client.post(
            f"/api/v1/milestones/{milestone.pk}/request-changes/",
            {"categories": [], "note": "n/a"},
            format="json",
        )
        assert response.status_code == 403

    def test_approval_survives_a_missing_payments_app(
        self, api_client, milestone, engagement, monkeypatch
    ):
        api_client.force_authenticate(user=engagement.provider)
        api_client.post(f"/api/v1/milestones/{milestone.pk}/submit/")
        monkeypatch.setitem(sys.modules, "apps.payments.services", None)
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(f"/api/v1/milestones/{milestone.pk}/approve/")
        assert response.status_code == 200
        milestone.refresh_from_db()
        assert milestone.status == "done"
        assert milestone.paid_at is None  # release hook was unavailable

    def test_requote_resolution_by_a_stranger_is_404(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.provider)
        created = api_client.post(
            f"/api/v1/engagements/{engagement.pk}/requotes/",
            {"new_total": "24800.00", "reason": "Scope grew"},
            format="json",
        ).json()
        api_client.force_authenticate(user=UserFactory())
        assert api_client.post(f"/api/v1/requotes/{created['id']}/approve/").status_code == 404
