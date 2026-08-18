"""The studio's WebSocket: presence and live invalidation for everyone editing.

Delivery only, like the user socket next door: edits are HTTP writes; this socket tells
the *other* editors what happened (`draft.changed`, `published`, `discarded`,
`site.purged`, `site.warmed`) and keeps a presence roster (who is on which page, with
what selected) so two people do not silently overwrite one another.
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache
from django.utils import timezone

from .events import GROUP

PRESENCE_TTL = 60
INDEX_KEY = "studio:presence-index"


def presence_key(sid) -> str:
    return f"studio:presence:{sid}"


def _read_roster() -> list[dict]:
    """Every editor with a live presence record."""
    sids = cache.get(INDEX_KEY) or []
    records = cache.get_many([presence_key(sid) for sid in sids])
    alive = [sid for sid in sids if presence_key(sid) in records]
    if alive != sids:
        cache.set(INDEX_KEY, alive, timeout=None)
    return [records[presence_key(sid)] for sid in alive]


def _write_presence(sid, record: dict) -> None:
    cache.set(presence_key(sid), record, timeout=PRESENCE_TTL)
    sids = cache.get(INDEX_KEY) or []
    if sid not in sids:
        cache.set(INDEX_KEY, [*sids, sid], timeout=None)


def _clear_presence(sid) -> None:
    cache.delete(presence_key(sid))
    sids = cache.get(INDEX_KEY) or []
    if sid in sids:
        cache.set(INDEX_KEY, [s for s in sids if s != sid], timeout=None)


class StudioConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        session = self.scope.get("studio_session")
        if session is None:
            # Accept, then close with the auth code: a close before accept reaches the
            # browser as an opaque 1006 and the client cannot tell "log in again" from
            # "the server is down".
            await self.accept()
            await self.close(code=4401)
            return
        self.session = session
        self.sid = session.pk
        self.editor = session.user.display_name
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()
        record = self._record(page="", selection=None, client="")
        await database_sync_to_async(_write_presence)(self.sid, record)
        roster = await database_sync_to_async(_read_roster)()
        await self.send_json({"type": "hello", "you": record, "editors": roster})
        await self.channel_layer.group_send(
            GROUP, {"type": "studio.event", "event": {"type": "presence.update", **record}}
        )

    async def disconnect(self, code):
        if not hasattr(self, "sid"):
            return
        await self.channel_layer.group_discard(GROUP, self.channel_name)
        await database_sync_to_async(_clear_presence)(self.sid)
        await self.channel_layer.group_send(
            GROUP,
            {
                "type": "studio.event",
                "event": {"type": "presence.leave", "sid": self.sid, "editor": self.editor},
            },
        )

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "ping":
            # A heartbeat also refreshes the presence record so an idle tab stays listed.
            record = await database_sync_to_async(cache.get)(presence_key(self.sid))
            if record:
                await database_sync_to_async(_write_presence)(self.sid, record)
            await self.send_json({"type": "pong"})
        elif kind == "presence":
            record = self._record(
                page=str(content.get("page") or "")[:120],
                selection=content.get("selection"),
                client=str(content.get("client") or "")[:64],
            )
            await database_sync_to_async(_write_presence)(self.sid, record)
            await self.channel_layer.group_send(
                GROUP, {"type": "studio.event", "event": {"type": "presence.update", **record}}
            )
        elif kind == "roster":
            roster = await database_sync_to_async(_read_roster)()
            await self.send_json({"type": "presence", "editors": roster})

    async def decode_json(self, text_data):
        try:
            return json.loads(text_data)
        except json.JSONDecodeError:
            return {}

    async def studio_event(self, event):
        await self.send_json(event["event"])

    def _record(self, *, page, selection, client) -> dict:
        return {
            "sid": self.sid,
            "editor": self.editor,
            "page": page,
            "selection": selection,
            "client": client,
            "at": timezone.now().isoformat(),
        }
