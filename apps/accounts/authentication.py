"""Clerk session-token authentication for DRF.

The Next.js frontend signs users in through Clerk (email + Google). Every API request
carries `Authorization: Bearer <clerk session JWT>`; we verify it against Clerk's JWKS
(RS256), then map the token's `sub` (Clerk user id) to a local User row, creating it on
first sight (JIT provisioning). Clerk webhooks (Stage 2) keep profile fields in sync.
"""

import logging

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)

_jwks_client = None


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.CLERK_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_clerk_token(token):
    """Verify a Clerk session JWT against the JWKS and return its claims.

    The single definition of "is this token acceptable", shared by DRF and the
    WebSocket middleware so the two transports cannot drift into accepting
    different tokens. Raises `jwt.PyJWTError` on every rejection, including an
    unauthorized `azp` — callers map that to their own transport's failure mode.
    """
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=settings.CLERK_ISSUER or None,
        options={"require": ["exp", "sub"], "verify_aud": False},
        leeway=5,
    )
    azp = claims.get("azp")
    if azp and settings.CLERK_AUTHORIZED_PARTIES and azp not in settings.CLERK_AUTHORIZED_PARTIES:
        raise jwt.InvalidTokenError("Token azp not in authorized parties.")
    return claims


class ClerkAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header.")
        if not settings.CLERK_JWKS_URL:
            # Clerk not configured (e.g. fresh checkout without .env) — treat as anonymous.
            return None

        token = header[1].decode()
        try:
            claims = verify_clerk_token(token)
        except jwt.PyJWTError as exc:
            raise exceptions.AuthenticationFailed(f"Invalid Clerk token: {exc}") from exc

        user = self._get_or_provision_user(claims)
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User account is disabled.")
        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"

    @staticmethod
    def _get_or_provision_user(claims):
        User = get_user_model()
        clerk_id = claims["sub"]
        try:
            return User.objects.get(clerk_id=clerk_id)
        except User.DoesNotExist:
            pass

        # JIT provisioning. Session tokens may omit email unless the Clerk JWT template
        # includes it; the user.created webhook backfills real values shortly after.
        email = claims.get("email") or f"{clerk_id}@pending.clerk.local"
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "clerk_id": clerk_id,
                "first_name": claims.get("first_name", "") or "",
                "last_name": claims.get("last_name", "") or "",
            },
        )
        if user.clerk_id is None:
            user.clerk_id = clerk_id
            user.save(update_fields=["clerk_id"])
        if created and user.has_placeholder_email:
            # Fetch the real profile now rather than leaving a synthetic address
            # for the UI (and, on machines without a webhook tunnel, forever).
            from .clerk_sync import backfill_user

            backfill_user(user)
        return user
