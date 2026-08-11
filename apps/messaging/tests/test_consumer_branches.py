"""Consumer signal paths: typing relay, read cursors and malformed frames."""

import json

import pytest
from channels.db import database_sync_to_async
from channels.testing.websocket import WebsocketCommunicator  # avoids daphne import

from apps.accounts.factories import UserFactory
from apps.messaging.consumers import UserConsumer
from apps.messaging.models import Thread, ThreadParticipant


def _make_thread():
    sender = UserFactory(role="client")
    other = UserFactory(role="architect")
    thread = Thread.objects.create()
    ThreadParticipant.objects.create(thread=thread, user=sender)
    ThreadParticipant.objects.create(thread=thread, user=other)
    return sender, other, thread


async def _connect(user):
    communicator = WebsocketCommunicator(UserConsumer.as_asgi(), "/ws/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def _drain(socket):
    """Discard queued frames (connect-time presence broadcasts arrive on
    whichever counterpart socket is already open)."""
    while not await socket.receive_nothing(timeout=0.1):
        await socket.receive_from()


@pytest.mark.django_db(transaction=True)
async def test_typing_relays_to_the_other_participant():
    sender, other, thread = await database_sync_to_async(_make_thread)()
    sender_socket = await _connect(sender)
    other_socket = await _connect(other)
    await _drain(other_socket)

    await sender_socket.send_to(json.dumps({"type": "typing", "thread_id": thread.pk}))
    event = json.loads(await other_socket.receive_from())
    assert event == {"type": "typing", "thread_id": thread.pk, "user_id": sender.pk}

    await sender_socket.disconnect()
    await other_socket.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_typing_without_a_reachable_thread_relays_nothing():
    sender, other, thread = await database_sync_to_async(_make_thread)()
    sender_socket = await _connect(sender)
    other_socket = await _connect(other)
    await _drain(other_socket)

    await sender_socket.send_to(json.dumps({"type": "typing"}))  # no thread_id
    await sender_socket.send_to(json.dumps({"type": "typing", "thread_id": 999999}))  # not a member
    await sender_socket.send_to("{ not json }")  # malformed frame is dropped
    await sender_socket.send_to(json.dumps({"type": "unknown-signal"}))

    assert await other_socket.receive_nothing(timeout=0.2)

    await sender_socket.disconnect()
    await other_socket.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_mark_read_moves_the_read_cursor():
    sender, other, thread = await database_sync_to_async(_make_thread)()
    socket = await _connect(sender)

    await socket.send_to(json.dumps({"type": "mark_read", "thread_id": thread.pk}))
    await socket.send_to(json.dumps({"type": "ping"}))  # round-trip so mark_read has landed
    assert json.loads(await socket.receive_from())["type"] == "pong"

    participant = await database_sync_to_async(ThreadParticipant.objects.get)(
        thread=thread, user=sender
    )
    assert participant.last_read_at is not None

    await socket.disconnect()
