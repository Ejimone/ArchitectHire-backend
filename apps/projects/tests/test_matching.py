import pytest
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.jurisdictions.models import State
from apps.projects.models import Project


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog,providers")


def make_architect(state_codes, email=None, **profile_kwargs):
    from apps.providers.models import ArchitectProfile

    user = UserFactory(role="architect", **({"email": email} if email else {}))
    defaults = {"onboarding_status": "approved", "accepting_work": True, "capacity": 4}
    defaults.update(profile_kwargs)
    profile = ArchitectProfile.objects.create(user=user, **defaults)
    profile.licensed_states.set(State.objects.filter(code__in=state_codes))
    return profile


def make_estimate(api_client, state="CA"):
    response = api_client.post(
        "/api/v1/estimates/",
        {
            "project_type": "Residential",
            "scope": "ADU",
            "sqft": 640,
            "state": state,
            "timeline": "Standard (10–12 wks)",
            "addons": [],
        },
        format="json",
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.django_db
class TestMatchingEngine:
    def test_licensure_hard_filter_and_cap(self, seeded, api_client):
        make_architect(["CA"], hourly_rate=135, engagement_mode="both", rating=4.9)
        make_architect(["CA"], rating=4.8)
        make_architect(["CA"], rating=4.7)
        make_architect(["CA"], rating=3.0)  # 4th CA architect — must be cut by the cap
        make_architect(["TX"])  # wrong state — must never match

        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        estimate_id = make_estimate(api_client)
        response = api_client.post("/api/v1/projects/", {"estimate_id": estimate_id}, format="json")
        assert response.status_code == 201
        body = response.json()

        assert len(body["matches"]) == 3
        assert body["matches"][0]["tag"] == "BEST MATCH"
        assert body["status"] == "choosing_architect"
        assert {m["tag"] for m in body["matches"]} <= {"BEST MATCH", "STRONG", "HOURLY OPTION"}

    def test_no_matches_when_no_licensed_architects(self, seeded, api_client):
        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        estimate_id = make_estimate(api_client, state="WY")
        response = api_client.post("/api/v1/projects/", {"estimate_id": estimate_id}, format="json")
        assert response.status_code == 201
        assert response.json()["matches"] == []

    def test_estimate_cannot_be_claimed_twice(self, seeded, api_client):
        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        estimate_id = make_estimate(api_client)
        assert (
            api_client.post(
                "/api/v1/projects/", {"estimate_id": estimate_id}, format="json"
            ).status_code
            == 201
        )
        assert (
            api_client.post(
                "/api/v1/projects/", {"estimate_id": estimate_id}, format="json"
            ).status_code
            == 400
        )

    def test_at_capacity_architect_excluded(self, seeded, api_client):
        profile = make_architect(["CA"], capacity=1)
        busy_client = UserFactory(role="client")
        Project.objects.create(
            owner=busy_client,
            title="Busy · California",
            project_type="Residential",
            scope="ADU",
            sqft=800,
            state=State.objects.get(code="CA"),
            status="underway",
            architect=profile.user,
        )
        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        estimate_id = make_estimate(api_client)
        response = api_client.post("/api/v1/projects/", {"estimate_id": estimate_id}, format="json")
        matched = {m["architect_name"] for m in response.json()["matches"]}
        full_name = profile.user.get_full_name() or profile.user.email
        assert full_name not in matched


@pytest.mark.django_db
class TestLeadAndHireFlow:
    def test_lead_accept_decline_undo_and_hire(self, seeded, api_client):
        profile = make_architect(["CA"], hourly_rate=135)
        owner = UserFactory(role="client")
        api_client.force_authenticate(user=owner)
        estimate_id = make_estimate(api_client)
        project = api_client.post(
            "/api/v1/projects/", {"estimate_id": estimate_id}, format="json"
        ).json()
        match_id = project["matches"][0]["id"]

        # Architect sees and responds to the lead
        api_client.force_authenticate(user=profile.user)
        leads = api_client.get("/api/v1/providers/me/leads/").json()
        assert leads[0]["id"] == match_id
        assert api_client.post(f"/api/v1/leads/{match_id}/decline/").json()["status"] == "declined"
        # Undo per the design: flip back to accept
        assert api_client.post(f"/api/v1/leads/{match_id}/accept/").json()["status"] == "accepted"

        # Client hires
        api_client.force_authenticate(user=owner)
        response = api_client.post(
            f"/api/v1/projects/{project['id']}/hire/", {"match_id": match_id}, format="json"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "underway"
        hired = next(m for m in body["matches"] if m["id"] == match_id)
        assert hired["status"] == "hired"

        # Lead can no longer be responded to
        api_client.force_authenticate(user=profile.user)
        assert api_client.post(f"/api/v1/leads/{match_id}/decline/").status_code == 409
