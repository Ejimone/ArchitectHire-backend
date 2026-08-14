"""The HTTP cron endpoint: the clock that replaces the beat process nobody runs.

The three jobs in `architecture_backend/celery.py`'s beat schedule have never fired in
production — most expensively `sweep_pending_payouts`, which is the only thing that ever
settles a payout whose provider account verified after the payout was created.
"""

from unittest.mock import patch

from django.test import override_settings
from django.urls import include, path

from apps.core.views import CRON_JOBS

# The production mount lives in architecture_backend/urls.py; pointing ROOT_URLCONF at
# this module keeps the endpoint's own tests independent of the root urlconf.
urlpatterns = [path("api/v1/", include("apps.core.urls"))]

URLS = override_settings(ROOT_URLCONF=__name__)
SECRET = override_settings(CRON_SECRET="s3cret")

SWEEP = "/api/v1/internal/cron/sweep-pending-payouts/"


# --- The schedule ------------------------------------------------------------


def test_every_beat_job_is_reachable_over_http():
    """Parity with `app.conf.beat_schedule` — a job missing here silently never runs."""
    assert set(CRON_JOBS) == {
        "rebuild-search-index",
        "sweep-pending-payouts",
        "cleanup-stale-data",
        "daily",
    }


def test_the_daily_batch_covers_every_individual_job():
    """Hobby plan fires one cron a day, so `daily` is the only trigger in production —
    a job left out of it never runs at all."""
    individual = {task for name, tasks in CRON_JOBS.items() if name != "daily" for task in tasks}
    assert set(CRON_JOBS["daily"]) == individual


# --- Dispatch ----------------------------------------------------------------


@URLS
@SECRET
def test_a_valid_secret_dispatches_the_job(client):
    with patch("apps.core.views.run_in_background") as run:
        response = client.post(SWEEP, headers={"x-cron-secret": "s3cret"})

    task = CRON_JOBS["sweep-pending-payouts"][0]
    assert response.status_code == 202
    assert response.json() == {"job": "sweep-pending-payouts", "started": [task.name]}
    assert run.call_args.args[1:] == (f"cron:{task.name}", task)


@URLS
@SECRET
def test_the_daily_trigger_dispatches_each_job_separately(client):
    """Separately, so one job raising cannot skip the two behind it."""
    with patch("apps.core.views.run_in_background") as run:
        response = client.post("/api/v1/internal/cron/daily/", headers={"x-cron-secret": "s3cret"})

    assert response.status_code == 202
    assert response.json()["started"] == [task.name for task in CRON_JOBS["daily"]]
    assert run.call_count == len(CRON_JOBS["daily"])


@URLS
@SECRET
def test_the_job_runs_in_process_rather_than_queueing_for_a_worker(client):
    """The whole point: a queued task would sit in Redis forever, exactly as before."""
    calls = []
    with patch.dict(CRON_JOBS, {"cleanup-stale-data": (lambda: calls.append("ran"),)}):
        response = client.post(
            "/api/v1/internal/cron/cleanup-stale-data/", headers={"x-cron-secret": "s3cret"}
        )

    assert response.status_code == 202
    assert calls == ["ran"]


@URLS
@SECRET
def test_an_unknown_job_lists_the_valid_ones(client):
    response = client.post(
        "/api/v1/internal/cron/drop-database/", headers={"x-cron-secret": "s3cret"}
    )

    assert response.status_code == 404
    assert response.json()["jobs"] == sorted(CRON_JOBS)


# --- The gate ----------------------------------------------------------------


@URLS
@SECRET
def test_a_wrong_secret_is_rejected(client):
    with patch("apps.core.views.run_in_background") as run:
        response = client.post(SWEEP, headers={"x-cron-secret": "guess"})

    assert response.status_code == 401
    run.assert_not_called()


@URLS
@SECRET
def test_a_missing_secret_header_is_rejected(client):
    assert client.post(SWEEP).status_code == 401


@URLS
@override_settings(CRON_SECRET="")
def test_a_blank_secret_disables_the_endpoint(client):
    """An unconfigured deployment must fail closed, not authenticate the empty header."""
    with patch("apps.core.views.run_in_background") as run:
        assert client.post(SWEEP, headers={"x-cron-secret": ""}).status_code == 503
        assert client.post(SWEEP).status_code == 503
    run.assert_not_called()
