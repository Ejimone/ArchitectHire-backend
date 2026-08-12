"""Push cache invalidation to the Next.js frontend.

Every content write already bumps the backend's Redis content version; this
module additionally pings the frontend's ``/api/revalidate`` route so the
owner sees admin edits on the live site immediately instead of waiting out
the 60-second ISR window. Fire-and-forget: a dead frontend never breaks a
save, and ISR remains the safety net.

The HTTP call runs on a Celery worker rather than in the request. It used to be
inline in a ``post_save`` signal, which put a 3-second timeout on the critical path
of every content save — tolerable for one edit, not for Studio's "publish everything"
button, which saves hundreds of rows in a loop.
"""

import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEBOUNCE_KEY = "cms:revalidate-ping"
DEBOUNCE_SECONDS = 1  # coalesce bursts (seed runs, bulk admin actions)
TIMEOUT_SECONDS = 3


def ping_frontend() -> bool:
    """POST to the frontend revalidation hook. Returns True if a ping was sent.

    Called from the Celery task, and directly as a fallback when the broker is
    unreachable. Does no debouncing of its own — :func:`schedule_ping` owns that,
    so the check happens once, in the request, before any queueing.
    """
    url = settings.FRONTEND_REVALIDATE_URL
    if not url:
        return False
    request = urllib.request.Request(
        url,
        method="POST",
        headers={"x-revalidate-secret": settings.REVALIDATE_SECRET},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            pass
    except (urllib.error.URLError, TimeoutError):
        return False
    return True


def schedule_ping() -> bool:
    """Queue a revalidation ping. Returns True if one was queued or sent.

    Debounces first so a bulk publish enqueues one task rather than hundreds.
    """
    if not settings.FRONTEND_REVALIDATE_URL:
        return False
    if not cache.add(DEBOUNCE_KEY, 1, timeout=DEBOUNCE_SECONDS):
        return False

    from apps.core.tasks import revalidate_frontend

    try:
        revalidate_frontend.delay()
    except Exception:  # noqa: BLE001 - any broker failure, not just OperationalError
        # No worker or no broker: fall back to the inline call. A slow save beats a
        # stale live site, and this path only runs when Celery is already broken.
        logger.warning("Revalidation task could not be queued; pinging inline.")
        return ping_frontend()
    return True
