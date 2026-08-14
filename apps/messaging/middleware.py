"""Clerk-JWT auth for WebSockets: /ws/?token=<clerk session JWT>."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class ClerkAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope["user"] = await self._resolve_user(scope)
        return await self.app(scope, receive, send)

    @database_sync_to_async
    def _resolve_user(self, scope):
        from django.conf import settings
        from django.contrib.auth.models import AnonymousUser

        from apps.accounts.authentication import ClerkAuthentication, verify_clerk_token

        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]
        if not token or not settings.CLERK_JWKS_URL:
            return AnonymousUser()
        try:
            user = ClerkAuthentication._get_or_provision_user(verify_clerk_token(token))
        except Exception as exc:
            # A socket that silently downgrades to anonymous is indistinguishable
            # from a signed-out user, which hides misconfiguration (a wrong JWKS
            # URL rejects every connection) until someone reads the frontend.
            logger.warning("WS auth rejected: %s", exc)
            return AnonymousUser()
        if not user.is_active:
            logger.warning("WS auth rejected: user %s is disabled", user.pk)
            return AnonymousUser()
        return user
