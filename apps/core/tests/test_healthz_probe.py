"""The `/healthz` readiness probe.

The behaviour under test is mostly about what the probe *refuses* to do: lie when the
database is gone, queue behind request traffic, or take the whole fleet out of rotation
because a shared dependency blinked.
"""

import asyncio
import time

import pytest

from apps.core import health


class _BrokenConnections:
    """Stands in for `django.db.connections` with a database that is gone."""

    def __getitem__(self, alias):
        raise OSError("connection is closed")

    def close_all(self):
        pass


class _BrokenCache:
    """Only `set` is needed — the check calls it first and never reaches `get`."""

    def set(self, *args, **kwargs):
        raise OSError("no redis")


@pytest.fixture(autouse=True)
def _fresh_probe():
    """The result is memoised for CACHE_SECONDS, so tests must not inherit each other's."""
    health.reset_cache()
    yield
    health.reset_cache()


def _probe():
    return asyncio.run(health.probe())


@pytest.mark.django_db
class TestProbe:
    def test_a_healthy_app_reports_ok(self):
        status, body = _probe()
        assert status == 200
        assert body.startswith(b"db=ok cache=ok started=")

    def test_the_body_names_when_the_process_started(self):
        """A deploy here is a `git push` and nothing reports back, so "did it land?" was
        answered by polling for a gap in this endpoint and hoping to catch a restart that
        can be over in seconds. The start time settles it in one request."""
        from datetime import UTC, datetime

        _, body = _probe()

        stamp = body.decode().split("started=")[1]
        started = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        assert started <= datetime.now(UTC)
        assert stamp.endswith("Z"), "UTC, so it can be compared against a push time"

    def test_a_dead_database_fails_the_probe(self, monkeypatch):
        """The regression this endpoint was rebuilt for.

        `/healthz` used to return a literal 200. When a burst killed the psycopg pool's
        connections it went on handing out dead ones — every request failing with
        PoolTimeout — while every container still reported itself healthy, so nothing was
        recycled and the outage lasted until someone restarted the app by hand.

        Patched at the module attribute rather than on the connection object: `_check`
        runs on its own thread and `connections` is a thread-local proxy, so a handle
        taken here is not the one that thread would resolve.
        """
        monkeypatch.setattr(health, "connections", _BrokenConnections())

        status, body = _probe()
        assert status == 503
        assert b"db=fail" in body

    def test_a_dead_cache_is_reported_but_does_not_pull_the_container(self, monkeypatch):
        """Asymmetric on purpose. Redis is shared, so failing the probe on it would take
        every container out of rotation at once and turn a blip into a total outage —
        removing the very containers that recover the instant Redis returns."""
        monkeypatch.setattr(health, "cache", _BrokenCache())

        status, body = _probe()
        assert status == 200
        assert body.startswith(b"db=ok cache=fail started=")

    def test_a_check_that_hangs_answers_unhealthy_rather_than_hanging(self, monkeypatch):
        """The pool's own timeout is 10s; a probe that waited for it would be killed by
        the platform before it could answer at all."""
        monkeypatch.setattr(health, "TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(health, "_check", lambda: time.sleep(0.4))

        status, body = _probe()
        assert status == 503
        assert body == b"db=timeout cache=unknown"
        # The check owns a single thread; let the abandoned one finish so it is free for
        # the next test — exactly as the next probe would have to wait for it in
        # production.
        time.sleep(0.45)

    def test_the_result_is_memoised(self, monkeypatch):
        """A 10s probe interval must not mean a query per probe."""
        calls = []
        monkeypatch.setattr(health, "_check", lambda: (calls.append(1), (200, b"db=ok"))[1])

        assert _probe() == (200, b"db=ok")
        assert _probe() == (200, b"db=ok")
        assert len(calls) == 1

    def test_the_memo_expires(self, monkeypatch):
        calls = []
        monkeypatch.setattr(health, "_check", lambda: (calls.append(1), (200, b"db=ok"))[1])
        monkeypatch.setattr(health, "CACHE_SECONDS", -1)  # already stale

        _probe()
        _probe()
        assert len(calls) == 2

    def test_concurrent_probes_pay_for_one_check(self, monkeypatch):
        """Several probes can land together; only the first should hit the database."""
        calls = []

        def slow_check():
            calls.append(1)
            __import__("time").sleep(0.05)
            return 200, b"db=ok cache=ok"

        monkeypatch.setattr(health, "_check", slow_check)

        async def race():
            return await asyncio.gather(*(health.probe() for _ in range(5)))

        results = asyncio.run(race())
        assert all(r == (200, b"db=ok cache=ok") for r in results)
        assert len(calls) == 1

    def test_the_probe_returns_its_connection_to_the_pool(self):
        """`request_finished` never fires for the probe's own thread, so without an
        explicit close it leaks one pooled connection per call — and with DB_POOL_MAX as
        low as 3 that drains the pool it is supposed to be watching."""
        closed = []
        original = health.connections.close_all
        health.connections.close_all = lambda: (closed.append(1), original())[1]
        try:
            health._check()
        finally:
            health.connections.close_all = original
        assert closed


@pytest.mark.django_db
class TestHealthzRouting:
    """`/healthz` is answered in asgi.py before Django, so ALLOWED_HOSTS and the shared
    sync thread — both of which have killed healthy containers — never see it."""

    @pytest.mark.parametrize("path", ["/healthz", "/healthz/"])
    def test_both_spellings_are_served(self, path, settings):
        from architecture_backend.asgi import http_application

        settings.ALLOWED_HOSTS = ["only-the-real-host"]
        sent = []

        async def run():
            await http_application(
                {"type": "http", "path": path, "headers": [(b"host", b"10.0.0.7")]},
                None,
                lambda message: _collect(sent, message),
            )

        asyncio.run(run())
        assert sent[0]["status"] == 200  # not the 400 DisallowedHost would give
        assert sent[1]["body"].startswith(b"db=ok cache=ok started=")
        assert (b"cache-control", b"no-store") in sent[0]["headers"]


async def _collect(sink, message):
    sink.append(message)
