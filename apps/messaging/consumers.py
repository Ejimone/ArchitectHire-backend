"""Single per-user WebSocket. Groups: user_{id}. WS is delivery-only —
messages are POSTed over HTTP; this socket receives events and lightweight
signals (typing, read cursors, presence heartbeats).
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache

PRESENCE_TTL = 60  # seconds
# Safety net on the per-user connection counter so a crashed worker can never
# pin someone "online" forever — the presence key itself still expires in 60s.
CONNECTIONS_TTL = 24 * 3600


def presence_key(user_id) -> str:
    return f"presence:{user_id}"


def connections_key(user_id) -> str:
    return f"presence_conn:{user_id}"


class UserConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or user.is_anonymous:
            # Accept first: closing before accept rejects the handshake with a
            # plain HTTP 403, which browsers surface as an opaque 1006 — the
            # 4401 auth contract only reaches clients on an accepted socket.
            await self.accept()
            await self.close(code=4401)
            return
        self.user = user
        self.group = f"user_{user.pk}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self._touch_presence()
        # Count open sockets per user: only the 0→1 and 1→0 transitions are
        # presence changes, so a second tab opening/closing stays silent.
        if await self._incr_connections():
            await self._broadcast_presence(online=True)

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
            if await self._decr_connections():
                await database_sync_to_async(cache.delete)(presence_key(self.user.pk))
                await self._broadcast_presence(online=False)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            payload = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        kind = payload.get("type")
        if kind == "ping":
            await self._touch_presence()
            await self.send(json.dumps({"type": "pong"}))
        elif kind == "typing":
            await self._forward_to_thread(
                payload.get("thread_id"),
                {
                    "type": "relay",
                    "event": {
                        "type": "typing",
                        "thread_id": payload.get("thread_id"),
                        "user_id": self.user.pk,
                    },
                },
            )
        elif kind == "mark_read":
            await self._mark_read(payload.get("thread_id"))

    # --- server-pushed events (via channel_layer.group_send) -----------------

    async def relay(self, event):
        await self.send(json.dumps(event["event"]))

    # --- helpers --------------------------------------------------------------

    async def _touch_presence(self):
        await database_sync_to_async(cache.set)(presence_key(self.user.pk), 1, PRESENCE_TTL)

    @database_sync_to_async
    def _incr_connections(self) -> bool:
        key = connections_key(self.user.pk)
        cache.add(key, 0, CONNECTIONS_TTL)
        return cache.incr(key) == 1

    @database_sync_to_async
    def _decr_connections(self) -> bool:
        key = connections_key(self.user.pk)
        try:
            remaining = cache.decr(key)
        except ValueError:  # key expired or never set — treat as last socket
            remaining = 0
        if remaining <= 0:
            cache.delete(key)
            return True
        return False

    async def _broadcast_presence(self, online: bool):
        event = {
            "type": "relay",
            "event": {"type": "presence", "user_id": self.user.pk, "online": online},
        }
        for user_id in await self._counterpart_ids():
            await self.channel_layer.group_send(f"user_{user_id}", event)

    @database_sync_to_async
    def _counterpart_ids(self):
        """Distinct users who share any thread with this user."""
        from .models import ThreadParticipant

        thread_ids = ThreadParticipant.objects.filter(user=self.user).values_list(
            "thread_id", flat=True
        )
        return list(
            ThreadParticipant.objects.filter(thread_id__in=list(thread_ids))
            .exclude(user=self.user)
            .values_list("user_id", flat=True)
            .distinct()
        )

    async def _forward_to_thread(self, thread_id, message):
        if not thread_id:
            return
        others = await self._thread_other_user_ids(thread_id)
        for user_id in others:
            await self.channel_layer.group_send(f"user_{user_id}", message)

    @database_sync_to_async
    def _thread_other_user_ids(self, thread_id):
        from .models import Thread

        thread = Thread.objects.filter(pk=thread_id, participants__user=self.user).first()
        if thread is None:
            return []
        return [u.pk for u in thread.other_participants(self.user)]

    @database_sync_to_async
    def _mark_read(self, thread_id):
        from django.utils import timezone

        from .models import ThreadParticipant

        ThreadParticipant.objects.filter(thread_id=thread_id, user=self.user).update(
            last_read_at=timezone.now()
        )
