"""Push cache invalidation to the Next.js frontend.

Every content write already bumps the backend's Redis content version; this module
additionally tells the frontend which of its cached pages to drop, so the owner sees
admin edits on the live site immediately instead of waiting out the ISR window.

Two properties matter more than latency:

* **A ping is coalesced, never lost.** Writes accumulate their tags in a Redis set and
  the first one claims a flush that fires at the *end* of the debounce window, so
  Studio's "publish everything" makes one HTTP call carrying the union of what changed.
  A leading-edge debounce does the opposite: the first writer wins and every tag that
  arrives behind it in the window is dropped, which is how a bulk publish could purge
  one page and leave the other forty stale.
* **A failed ping is loud, never fatal.** The save has already committed and ISR is
  still the safety net, so a frontend that is down — or that rejects our secret — is
  logged and swallowed rather than raised.

The HTTP call runs on `REVALIDATE_POOL`, not in the request: the flush sleeps out the
debounce window and then spends up to three seconds on the wire.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django_redis import get_redis_connection

from apps.core.background import REVALIDATE_POOL, run_in_background

logger = logging.getLogger(__name__)

# Tags waiting to be purged, and the claim that says a flush is already on its way.
PENDING_TAGS_KEY = "cms:revalidate-pending"
CLAIM_KEY = "cms:revalidate-claim"
# Long enough that a slow flush still finds its tags, short enough that a crashed one
# cannot hand an hour-old purge to the next writer.
PENDING_TTL_SECONDS = 60
# Past this, the purge is global in all but name; the catch-all costs the frontend the
# same rebuild without a request body that lists every page on the site.
MAX_TAGS = 64
TIMEOUT_SECONDS = 3
CATCH_ALL_TAGS = ("cms",)


def _debounce_seconds() -> float:
    """Read at call time, not import time, so a test can drive the window to zero."""
    return float(settings.REVALIDATE_DEBOUNCE_SECONDS)


def _key(name: str) -> str:
    """Namespace a raw-Redis key the way the cache backend namespaces its own.

    `get_redis_connection` hands back the unwrapped client, which does not apply
    KEY_PREFIX — and the test suite deliberately shares one Redis with the dev server.
    """
    return cache.make_key(name)


def ping_frontend(tags=()) -> bool:
    """POST the purge to the frontend hook. Returns True if the frontend took it.

    Does no debouncing of its own — :func:`schedule_ping` owns that. Empty `tags` means
    "everything": the frontend attaches the catch-all to every fetch it makes.
    """
    url = settings.FRONTEND_REVALIDATE_URL
    if not url:
        return False

    purge = sorted(tags) or list(CATCH_ALL_TAGS)
    request = urllib.request.Request(
        url,
        data=json.dumps({"tags": purge}).encode(),
        method="POST",
        headers={
            "x-revalidate-secret": settings.REVALIDATE_SECRET,
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            pass
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it has to be caught first: folding the two
        # together is how a permanently wrong REVALIDATE_SECRET stayed invisible.
        # ERROR rather than WARNING — a refusal is a misconfiguration, not a blip.
        logger.error(
            "Frontend rejected revalidation: HTTP %s %s",
            exc.code,
            exc.read(200).decode(errors="replace"),
        )
        return False
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("Frontend revalidation ping failed: %s", exc)
        return False
    logger.info("Revalidated %s frontend tag(s)", len(purge))
    return True


def schedule_ping(tags=()) -> bool:
    """Record `tags` as needing a purge and make sure one flush is on its way.

    Returns True for the caller that scheduled the flush. Everyone else gets False
    having still had their tags recorded: the coalescing happens in the flush, so
    losing this race costs a writer nothing.
    """
    if not settings.FRONTEND_REVALIDATE_URL:
        return False

    pending = sorted(tags) or list(CATCH_ALL_TAGS)
    client = get_redis_connection("default")
    client.sadd(_key(PENDING_TAGS_KEY), *pending)
    client.expire(_key(PENDING_TAGS_KEY), PENDING_TTL_SECONDS)

    window = _debounce_seconds()
    if not client.set(_key(CLAIM_KEY), 1, nx=True, px=max(1, round(window * 1000))):
        return False

    run_in_background(REVALIDATE_POOL, "revalidate", _flush_after_debounce)
    return True


def _flush_after_debounce() -> bool:
    """Wait out the debounce window, then send one ping carrying everything that piled
    up while we waited. Returns True if a ping went out."""
    time.sleep(_debounce_seconds())

    client = get_redis_connection("default")
    # Release the claim before draining, never after. A writer landing in that gap
    # claims a second flush which then finds an empty set — a wasted wake-up. The other
    # order drops the writer's tags with nothing scheduled to carry them.
    client.delete(_key(CLAIM_KEY))
    drained = client.spop(_key(PENDING_TAGS_KEY), MAX_TAGS + 1) or []
    if not drained:
        return False
    if len(drained) > MAX_TAGS:
        client.delete(_key(PENDING_TAGS_KEY))
        return ping_frontend(CATCH_ALL_TAGS)
    return ping_frontend(tag.decode() for tag in drained)
