"""The readiness probe behind ``/healthz``.

Three constraints shaped this, and they pull against each other:

1. **It must not lie.** The old probe returned a literal ``200`` without touching
   anything. When a burst killed the psycopg pool's connections, the pool went on handing
   out dead ones — every real request died with ``PoolTimeout`` — and every container
   still reported itself healthy, so nothing was ever recycled and the outage persisted
   until someone restarted the app by hand. Only a real query catches that.

2. **It must not be starvable.** Django runs sync views on one shared thread per worker,
   which is exactly what a request burst saturates — and a probe that times out during a
   burst gets healthy containers killed at the worst possible moment. So the check runs
   on its own dedicated thread, never the shared sync pool, and its result is cached for
   a few seconds so probe frequency is irrelevant.

3. **It must not cascade.** A probe strict enough to fail on any dependency will fail on
   *every* container at once the moment that shared dependency hiccups, turning a blip
   into a total outage. Hence the asymmetry below: a dead database fails the probe,
   because a dead pool is a per-container fault that only a restart clears. A dead Redis
   does not, because it is shared — taking the whole fleet out of rotation would remove
   the containers that will recover the instant Redis returns. It is still reported in
   the body, and ``/api/health/`` still fails on it for a human looking.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from django.core.cache import cache
from django.db import connections

logger = logging.getLogger(__name__)

#: How long a result is reused. Long enough that a 10s probe interval costs one query
#: per interval at most, short enough that a container is pulled promptly once it breaks.
CACHE_SECONDS = 5.0

#: Hard ceiling on the check itself. The pool's own `timeout` is 10s, so without this a
#: probe against an exhausted pool would hang rather than answer "not ready".
TIMEOUT_SECONDS = 3.0

#: One thread, owned by this module. The whole point is to be independent of the sync
#: thread that serves requests; sharing a pool with anything else would reintroduce the
#: starvation this exists to avoid.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ah-health")

#: When this process started, to the second, UTC.
#:
#: Deploys here are a `git push`: a hook on the VM pulls, rebuilds and restarts, and
#: nothing in that loop reports back. Answering "did my push actually land?" from the
#: outside meant polling for a gap in `/healthz` and hoping to catch a restart that can
#: be over in seconds — twice today that guess was wrong in both directions. An uptime
#: is not a secret and it settles the question in one request.
_STARTED = datetime.now(UTC).replace(microsecond=0)

_cached: tuple[float, int, bytes] | None = None
_lock = asyncio.Lock()


def _check() -> tuple[int, bytes]:
    """Run the dependency checks. Called on `_EXECUTOR`, never on the event loop."""
    db_ok = False
    try:
        # `connections["default"]` rather than the module-level `connection`: that is a
        # thread-local proxy, and this runs on a thread of our own.
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            db_ok = cursor.fetchone() == (1,)
    except Exception:
        logger.exception("Health probe: database check failed")
    finally:
        # CONN_MAX_AGE=0 closes connections on `request_finished`, which never fires for
        # this thread. Without an explicit close the probe leaks one pooled connection
        # per call — and with DB_POOL_MAX as low as 3, that empties the pool it is meant
        # to be watching.
        connections.close_all()

    cache_ok = False
    try:
        cache.set("health:ping", "pong", timeout=int(CACHE_SECONDS) + 5)
        cache_ok = cache.get("health:ping") == "pong"
    except Exception:
        logger.exception("Health probe: cache check failed")

    # Only the database gates readiness — see the module docstring on cascades.
    status = 200 if db_ok else 503
    body = (
        f"db={'ok' if db_ok else 'fail'} cache={'ok' if cache_ok else 'fail'} "
        f"started={_STARTED.isoformat().replace('+00:00', 'Z')}"
    )
    return status, body.encode()


async def probe() -> tuple[int, bytes]:
    """`(status, body)` for `/healthz`, cached and bounded."""
    global _cached

    now = time.monotonic()
    cached = _cached
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]

    async with _lock:
        # Re-read under the lock: several probes can arrive together, and only the first
        # should pay for the check.
        cached = _cached
        if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1], cached[2]

        loop = asyncio.get_running_loop()
        try:
            status, body = await asyncio.wait_for(
                loop.run_in_executor(_EXECUTOR, _check), timeout=TIMEOUT_SECONDS
            )
        except Exception as exc:
            # Covers the `wait_for` TimeoutError too. A check that cannot even finish is
            # the unhealthy answer, not an error page.
            logger.warning("Health probe did not complete: %r", exc)
            status, body = 503, b"db=timeout cache=unknown"

        _cached = (time.monotonic(), status, body)
        return status, body


def reset_cache() -> None:
    """Drop the memoised result. For tests, which must not see each other's answers."""
    global _cached
    _cached = None
