import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")

app = Celery("architecture_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Beat schedule lives in code (django-celery-beat deliberately avoided — plan risk R3).
app.conf.beat_schedule = {
    "rebuild-search-index-nightly": {
        "task": "apps.search.tasks.rebuild_search_index",
        "schedule": crontab(hour=3, minute=0),
    },
    "sweep-pending-payouts-hourly": {
        "task": "apps.payments.tasks.sweep_pending_payouts",
        "schedule": crontab(minute=15),
    },
    "cleanup-stale-data-daily": {
        "task": "apps.payments.tasks.cleanup_stale_data",
        "schedule": crontab(hour=4, minute=30),
    },
}
