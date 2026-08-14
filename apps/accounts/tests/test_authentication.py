"""Clerk session-token authentication.

Tokens are signed with a throwaway RSA key and verified through the real
PyJWT RS256 path; only the JWKS lookup (a network call) is stubbed.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from apps.accounts import authentication as auth_module
from apps.accounts.authentication import ClerkAuthentication
from apps.accounts.authentication import _get_jwks_client as build_jwks_client
from apps.accounts.factories import UserFactory

User = get_user_model()

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(key=SIGNING_KEY, **claims):
    payload = {"sub": "user_clerk_auth", "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, key, algorithm="RS256")


def request_with(token=None, header=None):
    factory = APIRequestFactory()
    if header is None and token is not None:
        header = f"Bearer {token}"
    extra = {"HTTP_AUTHORIZATION": header} if header is not None else {}
    return factory.get("/api/v1/auth/me/", **extra)


@pytest.fixture(autouse=True)
def clerk_configured(settings, monkeypatch):
    settings.CLERK_JWKS_URL = "https://clerk.test/.well-known/jwks.json"
    settings.CLERK_ISSUER = ""
    settings.CLERK_AUTHORIZED_PARTIES = ["http://localhost:3000"]
    monkeypatch.setattr(
        auth_module,
        "_get_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=SIGNING_KEY.public_key())
        ),
    )


class TestSharedVerifier:
    """`verify_clerk_token` is the single gate both HTTP and WebSocket auth use."""

    def test_valid_token_returns_its_claims(self):
        claims = auth_module.verify_clerk_token(
            make_token(sub="user_verifier", azp="http://localhost:3000")
        )
        assert claims["sub"] == "user_verifier"

    def test_unauthorized_party_raises_a_jwt_error(self):
        with pytest.raises(jwt.PyJWTError, match="azp not in authorized parties"):
            auth_module.verify_clerk_token(make_token(azp="https://evil.example.com"))

    def test_azp_is_unchecked_when_no_parties_are_configured(self, settings):
        settings.CLERK_AUTHORIZED_PARTIES = []
        claims = auth_module.verify_clerk_token(make_token(azp="https://anything.example.com"))
        assert claims["azp"] == "https://anything.example.com"


class TestJWKSClient:
    def test_client_is_built_once_and_cached(self, monkeypatch):
        monkeypatch.setattr(auth_module, "_jwks_client", None)
        first = build_jwks_client()
        assert isinstance(first, jwt.PyJWKClient)
        assert build_jwks_client() is first


class TestHeaderHandling:
    def test_no_header_is_anonymous(self):
        assert ClerkAuthentication().authenticate(request_with()) is None

    def test_non_bearer_scheme_is_ignored(self):
        assert ClerkAuthentication().authenticate(request_with(header="Basic abc")) is None

    def test_malformed_bearer_header_fails(self):
        with pytest.raises(exceptions.AuthenticationFailed, match="Invalid Authorization header"):
            ClerkAuthentication().authenticate(request_with(header="Bearer a b"))

    def test_unconfigured_clerk_is_anonymous(self, settings):
        settings.CLERK_JWKS_URL = ""
        assert ClerkAuthentication().authenticate(request_with(token="anything")) is None

    def test_authenticate_header(self):
        assert ClerkAuthentication().authenticate_header(request_with()) == "Bearer"


@pytest.mark.django_db
class TestTokenVerification:
    def test_valid_token_provisions_the_user_just_in_time(self):
        token = make_token(
            sub="user_jit_auth",
            email="jit-auth@example.com",
            first_name="Maya",
            last_name="Ellison",
        )
        user, returned_token = ClerkAuthentication().authenticate(request_with(token))
        assert returned_token == token
        assert user.clerk_id == "user_jit_auth"
        assert user.email == "jit-auth@example.com"
        assert user.first_name == "Maya"

    def test_token_without_email_uses_a_pending_placeholder(self):
        token = make_token(sub="user_no_email_auth")
        user, _ = ClerkAuthentication().authenticate(request_with(token))
        assert user.email == "user_no_email_auth@pending.clerk.local"

    def test_existing_clerk_user_is_reused(self):
        existing = UserFactory(clerk_id="user_known_auth")
        token = make_token(sub="user_known_auth", email=existing.email)
        user, _ = ClerkAuthentication().authenticate(request_with(token))
        assert user.pk == existing.pk

    def test_existing_email_without_clerk_id_is_backfilled(self):
        existing = UserFactory(email="backfill-auth@example.com", clerk_id=None)
        token = make_token(sub="user_backfill_auth", email="backfill-auth@example.com")
        user, _ = ClerkAuthentication().authenticate(request_with(token))
        assert user.pk == existing.pk
        assert user.clerk_id == "user_backfill_auth"

    def test_expired_token_is_rejected(self):
        token = make_token(exp=int(time.time()) - 3600)
        with pytest.raises(exceptions.AuthenticationFailed, match="Invalid Clerk token"):
            ClerkAuthentication().authenticate(request_with(token))

    def test_token_signed_by_another_key_is_rejected(self):
        token = make_token(key=OTHER_KEY)
        with pytest.raises(exceptions.AuthenticationFailed, match="Invalid Clerk token"):
            ClerkAuthentication().authenticate(request_with(token))

    def test_token_missing_required_claims_is_rejected(self):
        token = jwt.encode({"exp": int(time.time()) + 300}, SIGNING_KEY, algorithm="RS256")
        with pytest.raises(exceptions.AuthenticationFailed, match="Invalid Clerk token"):
            ClerkAuthentication().authenticate(request_with(token))

    def test_unknown_signing_key_is_rejected(self, monkeypatch):
        def _raise(token):
            raise jwt.PyJWKClientError("Unable to find a signing key that matches kid")

        monkeypatch.setattr(
            auth_module,
            "_get_jwks_client",
            lambda: SimpleNamespace(get_signing_key_from_jwt=_raise),
        )
        with pytest.raises(exceptions.AuthenticationFailed, match="Invalid Clerk token"):
            ClerkAuthentication().authenticate(request_with(make_token()))

    def test_unauthorized_party_is_rejected(self):
        token = make_token(sub="user_azp_auth", azp="https://evil.example.com")
        with pytest.raises(exceptions.AuthenticationFailed, match="azp not in authorized parties"):
            ClerkAuthentication().authenticate(request_with(token))

    def test_authorized_party_is_accepted(self):
        token = make_token(sub="user_azp_ok_auth", azp="http://localhost:3000")
        user, _ = ClerkAuthentication().authenticate(request_with(token))
        assert user.clerk_id == "user_azp_ok_auth"

    def test_disabled_account_is_rejected(self):
        UserFactory(clerk_id="user_disabled_auth", is_active=False)
        token = make_token(sub="user_disabled_auth")
        with pytest.raises(exceptions.AuthenticationFailed, match="account is disabled"):
            ClerkAuthentication().authenticate(request_with(token))


@pytest.mark.django_db
class TestJitBackfill:
    def test_new_placeholder_user_triggers_clerk_backfill(self, clerk_configured, monkeypatch):
        from apps.accounts import authentication as auth_mod

        calls = []
        monkeypatch.setattr(
            "apps.accounts.clerk_sync.backfill_user", lambda user: calls.append(user.pk)
        )
        token = make_token(sub="user_backfill_1")
        user, _ = auth_mod.ClerkAuthentication().authenticate(request_with(token))
        assert user.has_placeholder_email
        assert calls == [user.pk]

    def test_existing_user_is_not_backfilled_again(self, clerk_configured, monkeypatch):
        from apps.accounts import authentication as auth_mod

        calls = []
        monkeypatch.setattr(
            "apps.accounts.clerk_sync.backfill_user", lambda user: calls.append(user.pk)
        )
        token = make_token(sub="user_backfill_2")
        auth_mod.ClerkAuthentication().authenticate(request_with(token))  # creates + backfills
        auth_mod.ClerkAuthentication().authenticate(request_with(token))  # plain lookup
        assert len(calls) == 1
