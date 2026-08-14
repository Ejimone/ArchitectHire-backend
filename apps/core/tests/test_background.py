"""In-process background jobs: the replacement for a Celery worker we don't run.

The failure these guard against is silent: `task.delay()` succeeds against a live broker
with no worker behind it, so the work is simply never done and nothing logs.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db import transaction
from django.test import override_settings

from apps.core.background import (
    NOTIFY_POOL,
    _guarded,
    _guarded_on_pool_thread,
    post_commit_background,
    run_in_background,
)

EAGER = override_settings(BACKGROUND_TASKS_EAGER=True)
POOLED = override_settings(BACKGROUND_TASKS_EAGER=False)


# --- The guard ---------------------------------------------------------------


def test_a_job_returns_its_value():
    assert _guarded("job", lambda a, b: a + b, 1, b=2) == 3


def test_a_failing_job_is_logged_and_swallowed(caplog):
    """One bad job must not take the pool thread — or the caller — down with it."""

    def boom():
        raise ValueError("nope")

    assert _guarded("boom", boom) is None
    assert "Background job boom failed" in caplog.text


def test_the_pool_entry_point_hands_back_its_db_connection():
    """CONN_MAX_AGE=0 relies on `request_finished`, which never fires off-request."""
    with patch("apps.core.background.connections") as connections:
        assert _guarded_on_pool_thread("job", lambda: "done") == "done"
    connections.close_all.assert_called_once_with()


def test_the_connection_is_returned_even_when_the_job_raises():
    with patch("apps.core.background.connections") as connections:
        _guarded_on_pool_thread("job", lambda: 1 / 0)
    connections.close_all.assert_called_once_with()


# --- Scheduling --------------------------------------------------------------


@EAGER
def test_eager_runs_inline_without_touching_the_pool():
    """Tests need synchronous effects; inline must NOT close the caller's connection."""
    calls = []
    with (
        patch.object(NOTIFY_POOL, "submit") as submit,
        patch("apps.core.background.connections") as connections,
    ):
        run_in_background(NOTIFY_POOL, "job", calls.append, "ran")

    assert calls == ["ran"]
    submit.assert_not_called()
    connections.close_all.assert_not_called()


@POOLED
def test_work_is_submitted_to_the_pool():
    with patch.object(NOTIFY_POOL, "submit") as submit:
        run_in_background(NOTIFY_POOL, "job", print, "hi")

    submit.assert_called_once()
    assert submit.call_args.args[0] is _guarded_on_pool_thread
    assert submit.call_args.args[1:] == ("job", print, "hi")


@POOLED
def test_a_shut_down_pool_falls_back_to_running_inline(caplog):
    """Interpreter shutdown rejects new work; a lost notification is worse than a slow one."""
    calls = []
    pool = MagicMock()
    pool.submit.side_effect = RuntimeError("cannot schedule new futures after shutdown")

    run_in_background(pool, "job", calls.append, "ran")

    assert calls == ["ran"]
    assert "running job inline" in caplog.text


# --- Post-commit sequencing --------------------------------------------------


@EAGER
@pytest.mark.django_db(transaction=True)
def test_work_is_deferred_until_the_transaction_commits():
    """Dispatching mid-transaction can announce state that never commits."""
    calls = []
    with transaction.atomic():
        post_commit_background(NOTIFY_POOL, "job", calls.append, "ran")
        assert calls == []  # still open — nothing has run
    assert calls == ["ran"]


@EAGER
@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_transaction_never_dispatches():
    calls = []
    with pytest.raises(RuntimeError), transaction.atomic():
        post_commit_background(NOTIFY_POOL, "job", calls.append, "ran")
        raise RuntimeError("rollback")
    assert calls == []
