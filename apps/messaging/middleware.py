"""Clerk-JWT auth for WebSockets: /ws/?token=<clerk session JWT>."""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async


class ClerkAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope["user"] = await self._resolve_user(scope)
        return await self.app(scope, receive, send)

    @database_sync_to_async
    def _resolve_user(self, scope):
        from django.contrib.auth.models import AnonymousUser

        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]
        if not token:
            return AnonymousUser()
        try:
            import jwt as pyjwt
            from django.conf import settings

            from apps.accounts.authentication import ClerkAuthentication, _get_jwks_client

            if not settings.CLERK_JWKS_URL:
                return AnonymousUser()
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            claims = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=settings.CLERK_ISSUER or None,
                options={"require": ["exp", "sub"], "verify_aud": False},
                leeway=5,
            )
            return ClerkAuthentication._get_or_provision_user(claims)
        except Exception:
            return AnonymousUser()
