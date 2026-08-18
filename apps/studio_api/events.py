"""Fan studio events out to every connected editor.

One group, `studio`: the editing team is a handful of people and every client filters
by page itself. `emit` never raises — Redis being down must cost the live cursor, not
the save that just succeeded.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)

GROUP = "studio"


def emit(event: dict) -> bool:
    """Broadcast `event` (a JSON-serialisable dict with a `type`). Returns True if sent."""
    payload = {**event, "at": timezone.now().isoformat()}
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(GROUP, {"type": "studio.event", "event": payload})
        return True
    except Exception as exc:  # any failure is the same non-event
        logger.warning("Studio event %s not delivered: %s", event.get("type"), exc)
        return False


def actor(request) -> dict:
    """Who did it, from a Studio request: name for humans, client id for echo suppression."""
    user = getattr(request, "user", None)
    return {
        "by": getattr(user, "display_name", "") or "",
        "client": request.headers.get("x-studio-client", ""),
    }
