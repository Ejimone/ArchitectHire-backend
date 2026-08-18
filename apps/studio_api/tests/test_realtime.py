"""Stage 5: tickets, the studio WebSocket, publish → purge confirmation, warm-up."""

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing.websocket import WebsocketCommunicator
from django.core.cache import cache
from django.core.signing import TimestampSigner

from apps.cms.models import FAQ, CopyBlock
from apps.core import revalidate
from apps.core.revalidate import ping_now, schedule_warm, warm_routes
from apps.studio_api import events
from apps.studio_api.consumers import INDEX_KEY, StudioConsumer, presence_key
from apps.studio_api.middleware import StudioTicketMiddleware
from apps.studio_api.models import StudioSession
from apps.studio_api.tickets import issue_ticket, redeem_ticket

TICKET = "/api/v1/studio/auth/ticket/"
MEDIA = "/api/v1/studio/media/"
PING = pytest.mark.usefixtures("ping_settings")


@pytest.fixture
def ping_settings(settings):
    settings.FRONTEND_REVALIDATE_URL = "http://frontend/api/revalidate"
    settings.FRONTEND_URL = "https://architecthire.com"
    settings.REVALIDATE_SECRET = "s3cret"
    settings.REVALIDATE_DEBOUNCE_SECONDS = 0


# --------------------------------------------------------------------- tickets ---


@pytest.mark.django_db
class TestTickets:
    def test_issue_and_redeem_round_trip(self, staff_user):
        session, _ = StudioSession.issue(staff_user)
        ticket = issue_ticket(session, "upload")
        assert redeem_ticket(ticket, "upload").pk == session.pk
        # Purpose-bound: an upload ticket does not open a socket.
        assert redeem_ticket(ticket, "ws") is None
        assert redeem_ticket("", "upload") is None
        assert redeem_ticket(ticket + "x", "upload") is None
        assert redeem_ticket(ticket, "nope") is None
        with pytest.raises(ValueError):
            issue_ticket(session, "nope")

    def test_a_revoked_or_non_staff_session_is_refused(self, staff_user):
        session, _ = StudioSession.issue(staff_user)
        ticket = issue_ticket(session, "ws")
        session.revoke()
        assert redeem_ticket(ticket, "ws") is None
        session2, _ = StudioSession.issue(staff_user)
        ticket2 = issue_ticket(session2, "ws")
        staff_user.is_staff = False
        staff_user.save()
        assert redeem_ticket(ticket2, "ws") is None

    def test_a_ticket_for_a_deleted_session_is_refused(self, staff_user):
        session, _ = StudioSession.issue(staff_user)
        ticket = issue_ticket(session, "ws")
        session.delete()
        assert redeem_ticket(ticket, "ws") is None

    def test_an_expired_ticket_is_refused(self, staff_user, monkeypatch):
        session, _ = StudioSession.issue(staff_user)
        old = TimestampSigner(salt="studio-ticket:ws").sign_object({"sid": session.pk})
        monkeypatch.setitem(
            __import__("apps.studio_api.tickets", fromlist=["PURPOSES"]).PURPOSES, "ws", -1
        )
        assert redeem_ticket(old, "ws") is None

    def test_the_endpoint_mints_tickets(self, studio_client):
        response = studio_client.post(TICKET, {"purpose": "upload"}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["purpose"] == "upload" and body["expires_in"] == 600
        assert redeem_ticket(body["ticket"], "upload") is not None
        assert studio_client.post(TICKET, {"purpose": "x"}, format="json").status_code == 400

    def test_an_upload_ticket_authenticates_the_upload_views_only(
        self, studio_client, api_client, image_upload
    ):
        ticket = studio_client.post(TICKET, {"purpose": "upload"}, format="json").json()["ticket"]
        api_client.credentials(HTTP_AUTHORIZATION=f"StudioTicket {ticket}")
        upload = api_client.post(
            MEDIA, {"slot_key": "landing:ticket-probe", "image": image_upload}, format="multipart"
        )
        assert upload.status_code == 200, upload.content
        # The rest of the API is off limits with a ticket.
        assert api_client.get("/api/v1/studio/pages/").status_code == 401
        api_client.credentials(HTTP_AUTHORIZATION="StudioTicket forged")
        assert api_client.get(MEDIA).status_code == 401
        # No credentials at all: both schemes decline and the request is anonymous.
        api_client.credentials()
        assert api_client.get(MEDIA).status_code == 401
        from apps.studio_api.authentication import StudioUploadTicketAuthentication

        assert StudioUploadTicketAuthentication().authenticate_header(None) == "StudioTicket"


# -------------------------------------------------------------------- consumer ---


async def _connect(session):
    communicator = WebsocketCommunicator(StudioConsumer.as_asgi(), "/ws/studio/")
    communicator.scope["studio_session"] = session
    connected, _ = await communicator.connect()
    assert connected
    return communicator


@pytest.mark.django_db(transaction=True)
async def test_studio_socket_presence_and_events(staff_user):
    session = await database_sync_to_async(lambda: StudioSession.issue(staff_user)[0])()
    await database_sync_to_async(cache.delete)(INDEX_KEY)

    one = await _connect(session)
    hello = await one.receive_json_from()
    assert hello["type"] == "hello"
    assert hello["you"]["editor"] == staff_user.display_name
    assert any(e["sid"] == session.pk for e in hello["editors"])
    joined = await one.receive_json_from()  # own presence.update broadcast
    assert joined["type"] == "presence.update"

    # A second editor sees the first in the roster and announces itself to both.
    two = await _connect(session)
    hello_two = await two.receive_json_from()
    assert len(hello_two["editors"]) >= 1
    await two.receive_json_from()  # two's own presence.update
    seen_by_one = await one.receive_json_from()
    assert seen_by_one["type"] == "presence.update"

    # Presence with a page and selection is stored and relayed.
    await two.send_json_to({"type": "presence", "page": "landing", "selection": {"kind": "copy"}})
    relayed = await one.receive_json_from()
    assert relayed["type"] == "presence.update" and relayed["page"] == "landing"
    await two.receive_json_from()  # two's own echo
    stored = await database_sync_to_async(cache.get)(presence_key(session.pk))
    assert stored["page"] == "landing"

    # Ping refreshes and answers; roster on demand; garbage is ignored.
    await one.send_json_to({"type": "ping"})
    assert (await one.receive_json_from())["type"] == "pong"
    await one.send_json_to({"type": "roster"})
    roster = await one.receive_json_from()
    assert roster["type"] == "presence"
    await one.send_to(text_data="not json")

    # A server-side emit reaches both.
    await get_channel_layer().group_send(
        "studio", {"type": "studio.event", "event": {"type": "draft.changed", "scope": "landing"}}
    )
    assert (await one.receive_json_from())["type"] == "draft.changed"
    assert (await two.receive_json_from())["type"] == "draft.changed"

    await two.disconnect()
    leave = await one.receive_json_from()
    assert leave["type"] == "presence.leave"
    await one.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_ping_with_no_presence_record_still_pongs(staff_user):
    session = await database_sync_to_async(lambda: StudioSession.issue(staff_user)[0])()
    one = await _connect(session)
    await one.receive_json_from()
    await one.receive_json_from()
    await database_sync_to_async(cache.delete)(presence_key(session.pk))
    await one.send_json_to({"type": "ping"})
    assert (await one.receive_json_from())["type"] == "pong"
    await one.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_anonymous_socket_is_closed_with_4401():
    communicator = WebsocketCommunicator(StudioConsumer.as_asgi(), "/ws/studio/")
    communicator.scope["studio_session"] = None
    connected, _ = await communicator.connect()
    assert connected
    closed = await communicator.receive_output()
    assert closed["type"] == "websocket.close" and closed["code"] == 4401
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_middleware_resolves_the_ticket(staff_user):
    session = await database_sync_to_async(lambda: StudioSession.issue(staff_user)[0])()
    ticket = issue_ticket(session, "ws")
    captured = {}

    async def app(scope, receive, send):
        captured["session"] = scope["studio_session"]

    await StudioTicketMiddleware(app)(
        {"type": "websocket", "query_string": f"ticket={ticket}".encode()}, None, None
    )
    assert captured["session"].pk == session.pk
    await StudioTicketMiddleware(app)({"type": "websocket", "query_string": b""}, None, None)
    assert captured["session"] is None


def test_roster_prunes_dead_sids():
    from apps.studio_api.consumers import _read_roster, _write_presence

    cache.delete(INDEX_KEY)
    _write_presence(1, {"sid": 1, "editor": "A"})
    _write_presence(2, {"sid": 2, "editor": "B"})
    cache.delete(presence_key(1))
    assert [r["sid"] for r in _read_roster()] == [2]
    assert cache.get(INDEX_KEY) == [2]


# ---------------------------------------------------------------------- events ---


@pytest.mark.django_db
class TestEvents:
    def test_emit_survives_a_dead_channel_layer(self, caplog):
        with patch("apps.studio_api.events.get_channel_layer", side_effect=RuntimeError("down")):
            assert events.emit({"type": "x"}) is False
        assert "not delivered" in caplog.text

    def test_emit_sends_to_the_group(self):
        assert events.emit({"type": "x"}) is True

    def test_writes_announce_themselves(self, studio_client):
        with patch("apps.studio_api.views.emit") as emit:
            row = CopyBlock.objects.create(scope="landing", key="ann", text="a")
            studio_client.patch(
                f"/api/v1/studio/rows/cms.copyblock/{row.pk}/",
                {"text": "b"},
                format="json",
                HTTP_X_STUDIO_CLIENT="tab-1",
            )
            event = emit.call_args.args[0]
            assert event["type"] == "draft.changed"
            assert event["client"] == "tab-1" and event["mode"] == "draft"
            assert event["scope"] == "landing" and event["op"] == "update"

            studio_client.patch(
                f"/api/v1/studio/rows/cms.copyblock/{row.pk}/?mode=live",
                {"text": "c"},
                format="json",
            )
            assert emit.call_args.args[0]["mode"] == "live"

            # Discarding a pending create announces "discarded" for that row.
            created = studio_client.post(
                "/api/v1/studio/rows/cms.faq/",
                {"scope": "landing", "question": "Q?", "answer": "A"},
                format="json",
            ).json()["object_id"]
            studio_client.delete(f"/api/v1/studio/rows/cms.faq/{created}/")
            assert emit.call_args.args[0]["op"] == "discarded"

    def test_reorder_and_discard_announce(self, studio_client):
        a = FAQ.objects.create(scope="landing", question="A?", answer="1", sort_order=0)
        b = FAQ.objects.create(scope="landing", question="B?", answer="2", sort_order=1)
        with patch("apps.studio_api.views.emit") as emit:
            studio_client.post(
                "/api/v1/studio/rows/cms.faq/reorder/?mode=live",
                {"ids": [b.pk, a.pk]},
                format="json",
            )
            assert emit.call_args.args[0]["op"] == "reorder"
            studio_client.patch(
                f"/api/v1/studio/rows/cms.faq/{a.pk}/", {"answer": "x"}, format="json"
            )
            studio_client.post("/api/v1/studio/discard/", {"scope": "landing"}, format="json")
            assert emit.call_args.args[0]["type"] == "discarded"
            # Discarding nothing says nothing.
            emit.reset_mock()
            studio_client.post("/api/v1/studio/discard/", {"scope": "landing"}, format="json")
            emit.assert_not_called()


# ------------------------------------------------------- purge confirmation ---


def _ok_response():
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"x-vercel-cache": "HIT"}
    return response


@PING
@pytest.mark.django_db
class TestPingNow:
    def test_purges_pending_and_given_tags_at_once(self):
        client = revalidate.get_redis_connection("default")
        client.delete(revalidate._key(revalidate.PENDING_TAGS_KEY))
        client.sadd(revalidate._key(revalidate.PENDING_TAGS_KEY), "cms:page:about")
        with (
            patch("urllib.request.urlopen", return_value=_ok_response()) as urlopen,
            patch("apps.studio_api.events.emit") as emit,
        ):
            result = ping_now({"cms:page:landing"})
        assert result["ok"] is True
        assert result["tags"] == ["cms:page:about", "cms:page:landing"]
        sent = json.loads(urlopen.call_args.args[0].data)
        assert sent["tags"] == ["cms:page:about", "cms:page:landing"]
        assert emit.call_args.args[0]["type"] == "site.purged"

    def test_a_wide_purge_collapses_to_the_catch_all(self):
        client = revalidate.get_redis_connection("default")
        client.delete(revalidate._key(revalidate.PENDING_TAGS_KEY))
        with (
            patch("urllib.request.urlopen", return_value=_ok_response()),
            patch("apps.studio_api.events.emit"),
        ):
            wide = ping_now({f"cms:page:p{i}" for i in range(revalidate.MAX_TAGS + 1)})
        assert wide["tags"] == ["cms"]
        client.sadd(revalidate._key(revalidate.PENDING_TAGS_KEY), *[f"t{i}" for i in range(80)])
        with (
            patch("urllib.request.urlopen", return_value=_ok_response()),
            patch("apps.studio_api.events.emit"),
        ):
            pending_wide = ping_now({"cms:page:landing"})
        assert pending_wide["tags"] == ["cms"]

    def test_a_dead_frontend_reports_not_ok(self):
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")),
            patch("apps.studio_api.events.emit"),
        ):
            result = ping_now({"cms:page:landing"})
        assert result["ok"] is False

    def test_not_configured(self, settings):
        settings.FRONTEND_REVALIDATE_URL = ""
        assert ping_now({"x"})["reason"] == "not-configured"

    def test_the_debounced_flush_announces_too(self):
        # BACKGROUND_TASKS_EAGER runs the flush inline, so patch before scheduling.
        client = revalidate.get_redis_connection("default")
        client.delete(revalidate._key(revalidate.PENDING_TAGS_KEY))
        with (
            patch("urllib.request.urlopen", return_value=_ok_response()),
            patch("apps.studio_api.events.emit") as emit,
        ):
            revalidate.schedule_ping({"cms:page:landing"})
        assert emit.call_args.args[0]["type"] == "site.purged"
        assert emit.call_args.args[0]["ok"] is True


@PING
@pytest.mark.django_db
class TestWarm:
    def test_warm_waits_for_the_page_to_stop_being_stale(self, monkeypatch):
        monkeypatch.setattr(revalidate, "WARM_INTERVAL_SECONDS", 0)
        states = iter(["STALE", "HIT", "MISS"])
        with (
            patch.object(revalidate, "_fetch_cache_state", side_effect=lambda url: next(states)),
            patch("apps.studio_api.events.emit") as emit,
        ):
            result = warm_routes(["/", "/about", None, "/"])
        assert result["routes"] == ["/", "/about"]
        assert emit.call_args.args[0]["type"] == "site.warmed"

    def test_warm_gives_up_on_a_page_that_never_rebuilds(self, monkeypatch):
        monkeypatch.setattr(revalidate, "WARM_INTERVAL_SECONDS", 0)
        with (
            patch.object(revalidate, "_fetch_cache_state", return_value="STALE"),
            patch("apps.studio_api.events.emit"),
        ):
            assert warm_routes(["/"])["routes"] == []

    def test_warm_needs_a_site_url(self, settings):
        settings.FRONTEND_URL = ""
        assert warm_routes(["/"]) == {"routes": [], "ms": 0}

    def test_fetch_cache_state(self):
        with patch("urllib.request.urlopen", return_value=_ok_response()):
            assert revalidate._fetch_cache_state("https://x/") == "HIT"
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")):
            assert revalidate._fetch_cache_state("https://x/") == "ERROR"

    def test_schedule_warm_runs_on_the_pool(self):
        with patch.object(revalidate, "warm_routes", return_value={"routes": [], "ms": 0}) as warm:
            schedule_warm(["/"])
        warm.assert_called_once_with(["/"])


@PING
@pytest.mark.django_db
def test_publish_reports_the_purge_and_schedules_the_warm(studio_client):
    row = CopyBlock.objects.create(scope="landing", key="pub-purge", text="a")
    studio_client.patch(
        f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "b"}, format="json"
    )
    with (
        patch("urllib.request.urlopen", return_value=_ok_response()),
        patch("apps.studio_api.views.schedule_warm") as warm,
        patch("apps.studio_api.views.emit") as emit,
    ):
        response = studio_client.post(
            "/api/v1/studio/publish/", {"scope": "landing"}, format="json"
        )
    body = response.json()
    assert body["purge"]["ok"] is True
    assert "cms:page:landing" in body["purge"]["tags"]
    assert body["scopes"] == ["landing"]
    warm.assert_called_once_with(["/"])
    assert emit.call_args.args[0]["type"] == "published"
