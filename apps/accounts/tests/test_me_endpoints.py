import pytest
from rest_framework.exceptions import ValidationError

from apps.accounts.factories import UserFactory
from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.providers.models import ArchitectProfile, ExpertProfile, OnboardingStatus


@pytest.mark.django_db
class TestMeEndpoint:
    def test_requires_auth(self, api_client):
        assert api_client.get("/api/v1/auth/me/").status_code == 401

    def test_get_me(self, auth_client, user):
        response = auth_client.get("/api/v1/auth/me/")
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == user.email
        assert body["role"] == "client"

    def test_patch_profile(self, auth_client):
        response = auth_client.patch(
            "/api/v1/auth/me/",
            {"first_name": "Ada", "phone": "+1 555 0100"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["first_name"] == "Ada"
        assert body["phone"] == "+1 555 0100"

    @pytest.mark.parametrize("role", ["architect", "expert", "staff"])
    def test_role_is_read_only(self, auth_client, user, role):
        """Onboarding forwards whole form payloads here, so a crafted `user.role`
        field must be ignored rather than promote the account."""
        response = auth_client.patch("/api/v1/auth/me/", {"role": role}, format="json")
        assert response.status_code == 200
        assert response.json()["role"] == "client"
        user.refresh_from_db()
        assert user.role == User.Role.CLIENT

    def test_email_is_read_only(self, auth_client, user):
        response = auth_client.patch(
            "/api/v1/auth/me/", {"email": "evil@example.com"}, format="json"
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.email != "evil@example.com"


def test_validate_role_still_refuses_staff():
    """Defence in depth: `role` is read-only today, but the guard has to outlive
    anyone making it writable again."""
    serializer = UserSerializer(instance=User(is_staff=False))
    with pytest.raises(ValidationError):
        serializer.validate_role(User.Role.STAFF)
    assert serializer.validate_role(User.Role.ARCHITECT) == User.Role.ARCHITECT


@pytest.mark.django_db
class TestRoleEndpoint:
    @pytest.mark.parametrize("role", ["architect", "expert"])
    def test_a_client_can_become_a_provider(self, auth_client, user, role):
        response = auth_client.post("/api/v1/auth/me/role/", {"role": role}, format="json")
        assert response.status_code == 200
        assert response.json()["role"] == role
        user.refresh_from_db()
        assert user.role == role

    def test_role_is_required(self, auth_client):
        assert auth_client.post("/api/v1/auth/me/role/", {}, format="json").status_code == 400

    @pytest.mark.parametrize("role", ["staff", "client", "landlord"])
    def test_no_other_role_is_on_offer(self, auth_client, user, role):
        response = auth_client.post("/api/v1/auth/me/role/", {"role": role}, format="json")
        assert response.status_code == 403
        user.refresh_from_db()
        assert user.role == User.Role.CLIENT

    def test_a_provider_cannot_switch_sides(self, api_client):
        architect = UserFactory(role=User.Role.ARCHITECT)
        api_client.force_authenticate(user=architect)
        response = api_client.post("/api/v1/auth/me/role/", {"role": "expert"}, format="json")
        assert response.status_code == 403
        architect.refresh_from_db()
        assert architect.role == User.Role.ARCHITECT

    @pytest.mark.parametrize("model", [ArchitectProfile, ExpertProfile])
    def test_an_established_provider_profile_blocks_the_change(self, api_client, model):
        person = UserFactory(role=User.Role.CLIENT)
        model.objects.create(user=person, onboarding_status=OnboardingStatus.SUBMITTED)
        api_client.force_authenticate(user=person)
        response = api_client.post("/api/v1/auth/me/role/", {"role": "architect"}, format="json")
        assert response.status_code == 403

    def test_merely_opening_a_pro_screen_does_not_lock_the_role(self, api_client):
        """`providers.views._profile_for` get-or-creates an architect profile for
        whoever loads /pro — a browsing client must still be able to sign up."""
        person = UserFactory(role=User.Role.CLIENT)
        api_client.force_authenticate(user=person)
        api_client.get("/api/v1/providers/me/profile/")

        response = api_client.post("/api/v1/auth/me/role/", {"role": "architect"}, format="json")
        assert response.status_code == 200
        person.refresh_from_db()
        assert person.role == User.Role.ARCHITECT


@pytest.mark.django_db
class TestPreferencesEndpoint:
    def test_get_defaults(self, auth_client):
        response = auth_client.get("/api/v1/auth/me/preferences/")
        assert response.status_code == 200
        assert response.json() == {
            "milestone_updates": True,
            "new_messages": True,
            "requote_flags": True,
            "tips_marketing": False,
        }

    def test_patch_toggle(self, auth_client):
        response = auth_client.patch(
            "/api/v1/auth/me/preferences/",
            {"new_messages": False, "tips_marketing": True},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["new_messages"] is False
        assert body["tips_marketing"] is True
