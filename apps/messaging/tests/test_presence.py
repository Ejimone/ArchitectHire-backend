"""Presence transitions: only the 0→1 and 1→0 socket-count transitions
broadcast, so multi-tab users never flicker offline."""

import json

import pytest
from channels.db import database_sync_to_async
from channels.testing.websocket import WebsocketCommunicator  # avoids daphne import
from django.core.cache import cache

from apps.accounts.factories import UserFactory
from apps.messaging.consumers import UserConsumer, presence_key
from apps.messaging.models import Thread, ThreadParticipant


def _make_thread():
    client = UserFactory(role="client")
    architect = UserFactory(role="architect")
    thread = Thread.objects.create()
    ThreadParticipant.objects.create(thread=thread, user=client)
    ThreadParticipant.objects.create(thread=thread, user=architect)
    return client, architect, thread


async def _connect(user):
    communicator = WebsocketCommunicator(UserConsumer.as_asgi(), "/ws/")
    communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def _drain(socket):
    while not await socket.receive_nothing(timeout=0.1):
        await socket.receive_from()


async def _next_event(socket, event_type):
    """Read frames until one of the wanted type arrives."""
    while True:
        event = json.loads(await socket.receive_from())
        if event["type"] == event_type:
            return event


@pytest.mark.django_db(transaction=True)
async def test_first_connect_broadcasts_online_to_thread_counterparts():
    client, architect, _thread = await database_sync_to_async(_make_thread)()
    watcher = await _connect(architect)
    await _drain(watcher)

    socket = await _connect(client)
    event = await _next_event(watcher, "presence")
    assert event == {"type": "presence", "user_id": client.pk, "online": True}

    await socket.disconnect()
    await watcher.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_only_the_last_closing_tab_goes_offline():
    client, architect, _thread = await database_sync_to_async(_make_thread)()
    watcher = await _connect(architect)
    await _drain(watcher)

    tab_a = await _connect(client)
    await _next_event(watcher, "presence")  # online broadcast from the first tab
    tab_b = await _connect(client)  # second tab: silent
    assert await watcher.receive_nothing(timeout=0.2)

    await tab_a.disconnect()  # one of two tabs closing: still online
    assert await watcher.receive_nothing(timeout=0.2)
    assert await database_sync_to_async(cache.get)(presence_key(client.pk)) is not None

    await tab_b.disconnect()  # last tab: offline broadcast + presence cleared
    event = await _next_event(watcher, "presence")
    assert event == {"type": "presence", "user_id": client.pk, "online": False}
    assert await database_sync_to_async(cache.get)(presence_key(client.pk)) is None

    await watcher.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_expired_counter_treats_disconnect_as_last_socket():
    from apps.messaging.consumers import connections_key

    client, architect, _thread = await database_sync_to_async(_make_thread)()
    watcher = await _connect(architect)
    await _drain(watcher)

    socket = await _connect(client)
    await _next_event(watcher, "presence")
    # Simulate the safety-net TTL firing mid-session: the counter is gone, so
    # the disconnect must still resolve to "last socket" and go offline.
    await database_sync_to_async(cache.delete)(connections_key(client.pk))

    await socket.disconnect()
    event = await _next_event(watcher, "presence")
    assert event == {"type": "presence", "user_id": client.pk, "online": False}
    assert await database_sync_to_async(cache.get)(presence_key(client.pk)) is None

    await watcher.disconnect()
