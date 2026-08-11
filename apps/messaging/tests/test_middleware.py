"""WebSocket Clerk-token middleware: /ws/?token=<clerk session JWT>."""

import time
from types import SimpleNamespace

import jwt
import pytest
from channels.db import database_sync_to_async
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.accounts import authentication as auth_module
from apps.messaging.middleware import ClerkAuthMiddleware

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


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
async def test_invalid_token_is_anonymous():
    assert isinstance(await resolve(scope_for("not-a-jwt")), AnonymousUser)


@pytest.mark.django_db(transaction=True)
async def test_unconfigured_clerk_is_anonymous(settings):
    settings.CLERK_JWKS_URL = ""
    assert isinstance(await resolve(scope_for(make_token())), AnonymousUser)
