import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")

app = Celery("architecture_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Beat schedule is defined in code (django-celery-beat deliberately avoided — see plan risk R3).
# Entries are added as their tasks land in later stages, e.g.:
#   "rebuild-search-index-nightly": {
#       "task": "apps.search.tasks.rebuild_index",
#       "schedule": crontab(hour=3, minute=0),
#   },
app.conf.beat_schedule = {}
