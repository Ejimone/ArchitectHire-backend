"""WebSocket Clerk-token middleware: /ws/?token=<clerk session JWT>."""

import json
import logging
import time
from types import SimpleNamespace

import jwt
import pytest
from channels.db import database_sync_to_async
from channels.testing.websocket import WebsocketCommunicator  # avoids daphne import
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from apps.accounts import authentication as auth_module
from apps.accounts.authentication import ClerkAuthentication
from apps.accounts.factories import UserFactory
from apps.messaging.middleware import ClerkAuthMiddleware
from architecture_backend.asgi import websocket_application

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

ALLOWED_ORIGIN = b"http://localhost:3000"


class CapturingApp:
    """Stands in for the URLRouter so we can read the resolved scope."""

    def __init__(self):
        self.scope = None

    async def __call__(self, scope, receive, send):
        self.scope = scope
        return "handled"


def make_token(**claims):
    payload = {"sub": "user_ws_clerk", "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, SIGNING_KEY, algorithm="RS256")


def scope_for(token=None):
    query = f"token={token}".encode() if token else b""
    return {"type": "websocket", "path": "/ws/", "query_string": query}


@pytest.fixture(autouse=True)
def clerk_configured(settings, monkeypatch):
    settings.CLERK_JWKS_URL = "https://clerk.test/.well-known/jwks.json"
    settings.CLERK_ISSUER = ""
    settings.CLERK_AUTHORIZED_PARTIES = ["http://localhost:3000"]
    settings.WS_ALLOWED_ORIGINS = ["http://localhost:3000"]
    monkeypatch.setattr(
        auth_module,
        "_get_jwks_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=SIGNING_KEY.public_key())
        ),
    )


async def resolve(scope):
    app = CapturingApp()
    assert await ClerkAuthMiddleware(app)(scope, None, None) == "handled"
    return app.scope["user"]


def communicator_for(token=None, origin=ALLOWED_ORIGIN):
    """The production /ws/ stack, so the origin check is exercised too."""
    return WebsocketCommunicator(
        websocket_application(),
        f"/ws/?token={token}" if token else "/ws/",
        headers=[(b"origin", origin)] if origin else [],
    )


@pytest.mark.django_db(transaction=True)
async def test_valid_token_resolves_the_user():
    token = make_token(sub="user_ws_valid", email="ws-valid@example.com")
    user = await resolve(scope_for(token))
    assert user.clerk_id == "user_ws_valid"
    assert await database_sync_to_async(
        get_user_model().objects.filter(clerk_id="user_ws_valid").exists
    )()


@pytest.mark.django_db(transaction=True)
async def test_missing_token_is_anonymous():
    assert isinstance(await resolve(scope_for()), AnonymousUser)


@pytest.mark.django_db(transaction=True)
async def test_invalid_token_is_anonymous_and_logs_the_reason(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.messaging.middleware"):
        assert isinstance(await resolve(scope_for("not-a-jwt")), AnonymousUser)
    assert "WS auth rejected" in caplog.text


@pytest.mark.django_db(transaction=True)
async def test_unconfigured_clerk_is_anonymous(settings):
    settings.CLERK_JWKS_URL = ""
    assert isinstance(await resolve(scope_for(make_token())), AnonymousUser)


@pytest.mark.django_db(transaction=True)
async def test_token_minted_for_another_party_is_anonymous(caplog):
    token = make_token(sub="user_ws_azp", azp="https://evil.example.com")
    with caplog.at_level(logging.WARNING, logger="apps.messaging.middleware"):
        assert isinstance(await resolve(scope_for(token)), AnonymousUser)
    assert "azp not in authorized parties" in caplog.text
    # The rejection happens before provisioning, so no row is created either.
    assert not await database_sync_to_async(
        get_user_model().objects.filter(clerk_id="user_ws_azp").exists
    )()


@pytest.mark.django_db(transaction=True)
async def test_deactivated_user_is_anonymous(caplog):
    await database_sync_to_async(UserFactory)(
        clerk_id="user_ws_disabled", email="ws-disabled@example.com", is_active=False
    )
    with caplog.at_level(logging.WARNING, logger="apps.messaging.middleware"):
        user = await resolve(scope_for(make_token(sub="user_ws_disabled")))
    assert isinstance(user, AnonymousUser)
    assert "is disabled" in caplog.text


@pytest.mark.django_db(transaction=True)
async def test_both_transports_go_through_the_shared_verifier(monkeypatch):
    """HTTP and WebSocket previously duplicated the decode and drifted apart on
    which tokens they accepted; they must now share one entry point."""
    verified = []
    real_verify = auth_module.verify_clerk_token

    def recording_verify(token):
        verified.append(token)
        return real_verify(token)

    monkeypatch.setattr(auth_module, "verify_clerk_token", recording_verify)

    token = make_token(sub="user_ws_shared", email="ws-shared@example.com")
    await resolve(scope_for(token))
    request = APIRequestFactory().get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {token}")
    await database_sync_to_async(ClerkAuthentication().authenticate)(request)

    assert verified == [token, token]


async def test_disallowed_origin_never_reaches_the_consumer():
    communicator = communicator_for(make_token(), origin=b"https://evil.example.com")
    connected, _ = await communicator.connect()
    assert not connected
    await communicator.disconnect()


async def test_missing_origin_is_denied():
    """OriginValidator rejects a scope with no Origin header unless "*" is in the
    allow-list, so a non-browser client cannot skip the check by omitting it."""
    communicator = communicator_for(make_token(), origin=None)
    connected, _ = await communicator.connect()
    assert not connected
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_allowed_origin_connects_as_the_token_user():
    token = make_token(sub="user_ws_origin", email="ws-origin@example.com")
    communicator = communicator_for(token)
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_to(json.dumps({"type": "ping"}))
    assert json.loads(await communicator.receive_from())["type"] == "pong"

    await communicator.disconnect()
