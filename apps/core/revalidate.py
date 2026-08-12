"""Push cache invalidation to the Next.js frontend.

Every content write already bumps the backend's Redis content version; this
module additionally pings the frontend's ``/api/revalidate`` route so the
owner sees admin edits on the live site immediately instead of waiting out
the 60-second ISR window. Fire-and-forget: a dead frontend never breaks a
save, and ISR remains the safety net.
"""

import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

DEBOUNCE_KEY = "cms:revalidate-ping"
DEBOUNCE_SECONDS = 1  # coalesce bursts (seed runs, bulk admin actions)
TIMEOUT_SECONDS = 3


def ping_frontend() -> bool:
    """POST to the frontend revalidation hook. Returns True if a ping was sent."""
    url = settings.FRONTEND_REVALIDATE_URL
    if not url:
        return False
    if not cache.add(DEBOUNCE_KEY, 1, timeout=DEBOUNCE_SECONDS):
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
