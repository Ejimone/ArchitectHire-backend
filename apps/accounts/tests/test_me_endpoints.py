import pytest


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
            {"first_name": "Ada", "phone": "+1 555 0100", "role": "architect"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["first_name"] == "Ada"
        assert body["role"] == "architect"

    def test_cannot_self_assign_staff(self, auth_client):
        response = auth_client.patch("/api/v1/auth/me/", {"role": "staff"}, format="json")
        assert response.status_code == 400

    def test_email_is_read_only(self, auth_client, user):
        response = auth_client.patch(
            "/api/v1/auth/me/", {"email": "evil@example.com"}, format="json"
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.email != "evil@example.com"


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
