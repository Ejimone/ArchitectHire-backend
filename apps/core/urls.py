from django.urls import path

from .views import CronRunView

app_name = "core"

urlpatterns = [
    # "internal" as in machine-to-machine: secret-gated, never called by a browser.
    path("internal/cron/<slug:job>/", CronRunView.as_view(), name="cron"),
]
