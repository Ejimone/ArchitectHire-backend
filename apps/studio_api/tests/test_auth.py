import pytest
from django.utils import timezone

from apps.accounts.factories import UserFactory
from apps.studio_api.models import SESSION_LIFETIME, StudioSession

from .conftest import PASSWORD

LOGIN = "/api/v1/studio/auth/login/"
ME = "/api/v1/studio/auth/me/"
LOGOUT = "/api/v1/studio/auth/logout/"
PAGES = "/api/v1/studio/pages/"


@pytest.mark.django_db
class TestLogin:
    def test_staff_gets_a_token(self, api_client, staff_user):
        response = api_client.post(
            LOGIN, {"email": staff_user.email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["user"]["email"] == staff_user.email
        # The raw token is never stored, only its hash.
        assert not StudioSession.objects.filter(token_hash=body["token"]).exists()

    def test_wrong_password_rejected(self, api_client, staff_user):
        response = api_client.post(
            LOGIN, {"email": staff_user.email, "password": "nope"}, format="json"
        )
        assert response.status_code == 401

    def test_non_staff_gets_the_same_message_as_a_bad_password(self, api_client, db):
        user = UserFactory(email="client@example.com")
        user.set_password(PASSWORD)
        user.save()
        response = api_client.post(
            LOGIN, {"email": user.email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials."

    def test_inactive_staff_rejected(self, api_client, staff_user):
        staff_user.is_active = False
        staff_user.save()
        response = api_client.post(
            LOGIN, {"email": staff_user.email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 401

    def test_empty_body_rejected(self, api_client, db):
        assert api_client.post(LOGIN, {}, format="json").status_code == 401


@pytest.mark.django_db
class TestTokenAuthentication:
    def test_valid_token_reaches_the_api(self, studio_client):
        assert studio_client.get(PAGES).status_code == 200

    def test_no_credentials_rejected(self, api_client):
        assert api_client.get(PAGES).status_code in (401, 403)

    def test_other_scheme_is_ignored(self, api_client, studio_token):
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {studio_token}")
        assert api_client.get(PAGES).status_code in (401, 403)

    def test_scheme_without_a_token_rejected(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Studio ")
        assert api_client.get(PAGES).status_code == 401

    def test_unknown_token_rejected(self, api_client, db):
        api_client.credentials(HTTP_AUTHORIZATION="Studio not-a-real-token")
        assert api_client.get(PAGES).status_code == 401

    def test_revoked_token_rejected(self, api_client, staff_user):
        session, token = StudioSession.issue(staff_user)
        session.revoke()
        api_client.credentials(HTTP_AUTHORIZATION=f"Studio {token}")
        assert api_client.get(PAGES).status_code == 401

    def test_expired_token_rejected(self, api_client, staff_user):
        session, token = StudioSession.issue(staff_user)
        session.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        session.save()
        api_client.credentials(HTTP_AUTHORIZATION=f"Studio {token}")
        assert api_client.get(PAGES).status_code == 401

    def test_staff_revoked_after_login_rejected(self, api_client, staff_user):
        _session, token = StudioSession.issue(staff_user)
        staff_user.is_staff = False
        staff_user.save()
        api_client.credentials(HTTP_AUTHORIZATION=f"Studio {token}")
        assert api_client.get(PAGES).status_code == 401

    def test_session_slides_only_once_half_spent(self, api_client, staff_user):
        session, token = StudioSession.issue(staff_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Studio {token}")

        api_client.get(PAGES)
        session.refresh_from_db()
        fresh_expiry = session.expires_at

        session.expires_at = timezone.now() + timezone.timedelta(hours=1)
        session.save()
        api_client.get(PAGES)
        session.refresh_from_db()
        assert session.expires_at > fresh_expiry - SESSION_LIFETIME


@pytest.mark.django_db
class TestSessionEndpoints:
    def test_me_reports_the_signed_in_operator(self, studio_client, staff_user):
        body = studio_client.get(ME).json()
        assert body["email"] == staff_user.email
        assert body["name"] == staff_user.display_name

    def test_logout_revokes_the_session(self, studio_client):
        assert studio_client.post(LOGOUT).status_code == 204
        assert studio_client.get(ME).status_code == 401


@pytest.mark.django_db
def test_model_reprs(staff_user):
    session, _token = StudioSession.issue(staff_user)
    assert str(staff_user.pk) in str(session)
    assert session.is_active
