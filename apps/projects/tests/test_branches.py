"""Project model strings, matching score components and view/serializer guards."""

import uuid
from decimal import Decimal

import pytest
from django.contrib.admin.sites import site
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.catalog.models import ProjectType
from apps.jurisdictions.models import State
from apps.projects.admin import EstimateAdmin
from apps.projects.matching import find_matches
from apps.projects.models import Estimate, Match, Project
from apps.providers.models import ArchitectProfile


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog,providers")


def make_project(owner=None, **kwargs):
    defaults = {
        "owner": owner or UserFactory(role="client"),
        "title": "ADU · California",
        "project_type": "Residential",
        "scope": "ADU",
        "sqft": 640,
        "state": State.objects.get(code="CA"),
    }
    defaults.update(kwargs)
    return Project.objects.create(**defaults)


def make_architect(**profile_kwargs):
    user = UserFactory(role="architect")
    defaults = {"onboarding_status": "approved", "accepting_work": True, "capacity": 4}
    defaults.update(profile_kwargs)
    profile = ArchitectProfile.objects.create(user=user, **defaults)
    profile.licensed_states.set(State.objects.filter(code="CA"))
    return profile


def test_estimate_str():
    estimate = Estimate(
        scope="ADU",
        sqft=640,
        state=State(code="CA"),
        low=Decimal("19688"),
        high=Decimal("23112"),
    )
    assert str(estimate) == "ADU · 640 sf · CA ($19688–$23112)"


def test_project_str():
    assert str(Project(title="ADU · California")) == "ADU · California"


def test_match_str():
    match = Match(
        project=Project(title="ADU · California"),
        architect=UserFactory.build(email="maya@example.com"),
        score=92,
    )
    assert str(match) == "ADU · California ↔ maya@example.com (92%)"


def test_estimates_are_read_only_in_admin():
    assert EstimateAdmin(Estimate, site).has_add_permission(None) is False


@pytest.mark.django_db
class TestMatchScoring:
    def test_project_type_specialisation_adds_points(self, seeded):
        project_type = ProjectType.objects.get(slug="backyard-adu")
        generalist = make_architect()
        specialist = make_architect()
        specialist.project_types.set([project_type])
        project = make_project(project_type_ref=project_type)

        scores = {entry["profile"].pk: entry for entry in find_matches(project)}
        assert scores[specialist.pk]["score"] > scores[generalist.pk]["score"]
        assert any("specialist" in reason for reason in scores[specialist.pk]["reasons"])

    def test_reputation_and_punctuality_add_points(self, seeded):
        plain = make_architect()
        reputable = make_architect(rating=Decimal("4.90"), review_count=31, on_time_rate=100)
        project = make_project()

        scores = {entry["profile"].pk: entry["score"] for entry in find_matches(project)}
        assert scores[reputable.pk] > scores[plain.pk]

    def test_a_single_free_slot_scores_below_real_headroom(self, seeded):
        roomy = make_architect(capacity=4)
        tight = make_architect(capacity=1)
        project = make_project()

        scores = {entry["profile"].pk: entry for entry in find_matches(project)}
        assert scores[roomy.pk]["score"] > scores[tight.pk]["score"]
        assert "Capacity to start now" in scores[roomy.pk]["reasons"]
        assert "Capacity to start now" not in scores[tight.pk]["reasons"]


@pytest.mark.django_db
class TestEstimateAndProjectGuards:
    def test_unknown_addons_are_rejected(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/estimates/",
            {
                "project_type": "Residential",
                "scope": "ADU",
                "sqft": 640,
                "state": "CA",
                "timeline": "Standard (10–12 wks)",
                "addons": ["moon-base"],
            },
            format="json",
        )
        assert response.status_code == 400
        assert "Unknown add-ons" in str(response.json()["addons"][0])

    def test_unknown_estimate_cannot_be_claimed(self, seeded, api_client):
        api_client.force_authenticate(user=UserFactory(role="client"))
        response = api_client.post(
            "/api/v1/projects/", {"estimate_id": str(uuid.uuid4())}, format="json"
        )
        assert response.status_code == 400
        assert "Unknown estimate" in str(response.json())

    def test_anonymous_estimate_is_adopted_on_claim(self, seeded, api_client):
        created = api_client.post(
            "/api/v1/estimates/",
            {
                "project_type": "Residential",
                "scope": "ADU",
                "sqft": 640,
                "state": "CA",
                "timeline": "Standard (10–12 wks)",
                "addons": [],
            },
            format="json",
        ).json()
        assert Estimate.objects.get(pk=created["id"]).user is None

        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        response = api_client.post(
            "/api/v1/projects/", {"estimate_id": created["id"]}, format="json"
        )
        assert response.status_code == 201
        assert Estimate.objects.get(pk=created["id"]).user == owner


@pytest.mark.django_db
class TestProjectViews:
    def test_matches_endpoint_lists_the_project_matches(self, seeded, api_client):
        profile = make_architect()
        project = make_project()
        Match.objects.create(project=project, architect=profile.user, score=92, tag="BEST MATCH")

        api_client.force_authenticate(user=project.owner)
        body = api_client.get(f"/api/v1/projects/{project.pk}/matches/").json()
        assert [m["score"] for m in body] == [92]

    def test_hiring_twice_conflicts(self, seeded, api_client):
        profile = make_architect()
        project = make_project(status=Project.Status.UNDERWAY, architect=profile.user)
        match = Match.objects.create(project=project, architect=profile.user, score=92)

        api_client.force_authenticate(user=project.owner)
        response = api_client.post(
            f"/api/v1/projects/{project.pk}/hire/", {"match_id": match.pk}, format="json"
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "Project already underway."

    def test_lead_without_an_estimate_has_a_blank_range(self, seeded, api_client):
        profile = make_architect()
        project = make_project()
        Match.objects.create(project=project, architect=profile.user, score=92)

        api_client.force_authenticate(user=profile.user)
        body = api_client.get("/api/v1/providers/me/leads/").json()
        assert body[0]["estimate_range"] == ""
