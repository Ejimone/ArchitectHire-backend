"""Background work for core content plumbing."""

from celery import shared_task

from apps.core.revalidate import CATCH_ALL_TAGS, ping_frontend


@shared_task(ignore_result=True)
def revalidate_frontend(tags=None) -> bool:
    """Tell the Next.js frontend to drop the cached pages behind `tags`.

    The debounced flush runs on `REVALIDATE_POOL` rather than here; this survives so a
    deployment that really does run a worker can hand the HTTP call to it instead.
    Deliberately has no retry: the frontend's ISR window is the safety net, and a retry
    storm behind a down frontend would be worse than one missed purge.
    """
    return ping_frontend(tags or CATCH_ALL_TAGS)
