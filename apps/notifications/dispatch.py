"""How the rest of the codebase asks for a notification to go out.

Call `notify_soon(...)` — never `notify.delay(...)`. The deployment runs no Celery
worker, so `.delay()` returns happily and the task is never consumed; that is how every
in-app notification, Web Push and fallback email went missing in production while
nothing appeared in the logs.

`notify_soon` schedules delivery post-commit on the in-process pool, so it works with or
without a worker. Set `NOTIFY_VIA_CELERY=1` only in an environment that genuinely has
one running.
"""

import logging

from django.conf import settings

from apps.core.background import NOTIFY_POOL, post_commit_background

from .tasks import deliver, notify

logger = logging.getLogger(__name__)


def notify_soon(
    user_id: int, kind: str, title: str, body: str = "", data: dict | None = None
) -> None:
    """Deliver a notification after the current transaction commits.

    Post-commit matters: the fanout re-reads the row it is announcing, so dispatching
    mid-transaction can announce a state that never commits — or read a stale one.
    """
    if settings.NOTIFY_VIA_CELERY:
        try:
            notify.delay(user_id, kind, title, body, data)
            return
        except Exception:  # noqa: BLE001 — any broker failure, not just OperationalError
            logger.warning("Broker unavailable; delivering %s in-process", kind)

    post_commit_background(NOTIFY_POOL, f"notify:{kind}", deliver, user_id, kind, title, body, data)
