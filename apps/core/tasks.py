"""Background work for core content plumbing."""

from celery import shared_task

from apps.core.revalidate import ping_frontend


@shared_task(ignore_result=True)
def revalidate_frontend() -> bool:
    """Tell the Next.js frontend to drop its cached pages.

    Queued by `schedule_ping()` after a content write. Deliberately has no retry:
    the frontend's ISR window is the safety net, and a retry storm behind a down
    frontend would be worse than one missed purge.
    """
    return ping_frontend()
