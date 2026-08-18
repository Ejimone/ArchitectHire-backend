"""Ticket auth for the studio WebSocket: /ws/studio/?ticket=<ticket>."""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async


class StudioTicketMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope["studio_session"] = await self._resolve(scope)
        return await self.app(scope, receive, send)

    @database_sync_to_async
    def _resolve(self, scope):
        from .tickets import redeem_ticket

        query = parse_qs(scope.get("query_string", b"").decode())
        return redeem_ticket((query.get("ticket") or [""])[0], "ws")
