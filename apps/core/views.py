import hmac
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_202_ACCEPTED,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_503_SERVICE_UNAVAILABLE,
)
from rest_framework.views import APIView

from apps.core.background import NOTIFY_POOL, run_in_background
from apps.payments.tasks import cleanup_stale_data, sweep_pending_payouts
from apps.search.tasks import rebuild_search_index

logger = logging.getLogger(__name__)


def health(request):
    """Liveness/readiness probe: verifies database and Redis connectivity."""
    checks = {"db": False, "cache": False}
    status = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["db"] = cursor.fetchone() == (1,)
    except Exception:
        status = 503

    try:
        cache.set("health:ping", "pong", timeout=5)
        checks["cache"] = cache.get("health:ping") == "pong"
    except Exception:
        status = 503

    if not all(checks.values()):
        status = 503

    return JsonResponse({"status": "ok" if status == 200 else "degraded", **checks}, status=status)


# The beat schedule in architecture_backend/celery.py has no process running it, so the
# clock lives outside the deployment: Vercel Cron -> the frontend's /api/cron/<job> ->
# here. Keep these names in sync with the frontend's vercel.json.
#
# The values are the `@shared_task` objects themselves, deliberately. Calling one runs
# its body in-process; `.delay()` would hand it to a queue that no worker reads.
CRON_JOBS = {
    "rebuild-search-index": (rebuild_search_index,),
    "sweep-pending-payouts": (sweep_pending_payouts,),
    "cleanup-stale-data": (cleanup_stale_data,),
    # Vercel's Hobby plan caps a project at two cron jobs, each firing at most once a
    # day, so one daily invocation has to carry the whole schedule. The tasks are still
    # dispatched individually below, so one failing does not skip the others. On Pro,
    # point vercel.json at the individual names and give the payout sweep back its hour.
    "daily": (rebuild_search_index, sweep_pending_payouts, cleanup_stale_data),
}


class CronRunView(APIView):
    """Runs one scheduled job. Gated on a shared secret, not on a user session."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request, job):
        secret = settings.CRON_SECRET
        if not secret:
            # With no secret configured every caller looks authentic, so refuse outright
            # rather than run money-moving jobs for anyone who finds the URL.
            logger.error("CRON_SECRET not configured; refusing to run cron job %s", job)
            return Response(status=HTTP_503_SERVICE_UNAVAILABLE)

        # Bytes, not str: header values reach us latin-1 decoded and compare_digest
        # raises TypeError on any non-ASCII str.
        provided = request.headers.get("x-cron-secret", "")
        if not hmac.compare_digest(provided.encode(), secret.encode()):
            logger.warning("Rejected cron request for %s: bad secret", job)
            return Response(status=HTTP_401_UNAUTHORIZED)

        tasks = CRON_JOBS.get(job)
        if tasks is None:
            return Response(
                {"detail": f"Unknown job '{job}'.", "jobs": sorted(CRON_JOBS)},
                status=HTTP_404_NOT_FOUND,
            )

        # A payout sweep can outlast the caller's request timeout, and a timed-out cron
        # invocation is indistinguishable from a failed one. Answer now, work after.
        started = []
        for task in tasks:
            name = getattr(task, "name", None) or getattr(task, "__name__", job)
            run_in_background(NOTIFY_POOL, f"cron:{name}", task)
            started.append(name)
        return Response({"job": job, "started": started}, status=HTTP_202_ACCEPTED)
