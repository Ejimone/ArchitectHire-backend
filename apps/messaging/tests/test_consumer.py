"""Risk R1 smoke test: channels 4.3 consumer under Django 6.1 (in-memory layer)."""

import json

import pytest
from channels.layers import get_channel_layer
from channels.testing.websocket import WebsocketCommunicator  # avoids daphne import

from apps.accounts.factories import UserFactory
from apps.messaging.consumers import UserConsumer


@pytest.mark.django_db(transaction=True)
async def test_connect_ping_and_server_push():
    from channels.db import database_sync_to_async

    user = await database_sync_to_async(UserFactory)()

    communicator = WebsocketCommunicator(UserConsumer.as_asgi(), "/ws/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected

    # Client ping → pong (presence heartbeat)
    await communicator.send_to(json.dumps({"type": "ping"}))
    response = json.loads(await communicator.receive_from())
    assert response["type"] == "pong"

    # Server push via the channel layer group (what message fanout does)
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f"user_{user.pk}",
        {"type": "relay", "event": {"type": "message.new", "thread_id": 1}},
    )
    event = json.loads(await communicator.receive_from())
    assert event["type"] == "message.new"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_anonymous_rejected():
    from django.contrib.auth.models import AnonymousUser

    communicator = WebsocketCommunicator(UserConsumer.as_asgi(), "/ws/")
    communicator.scope["user"] = AnonymousUser()
    connected, _ = await communicator.connect()
    # The handshake is accepted so the 4401 close code reaches real browsers —
    # close-before-accept degrades to an opaque 1006 at the ASGI server.
    assert connected
    close = await communicator.receive_output()
    assert close == {"type": "websocket.close", "code": 4401}
