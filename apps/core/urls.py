from django.urls import path

from .views import CronRunView, private_file

app_name = "core"

urlpatterns = [
    # "internal" as in machine-to-machine: secret-gated, never called by a browser.
    path("internal/cron/<slug:job>/", CronRunView.as_view(), name="cron"),
    # Private files behind a signed, expiring token (see apps.core.storages).
    path("files/", private_file, name="private-file"),
]
