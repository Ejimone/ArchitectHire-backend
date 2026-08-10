from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


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
