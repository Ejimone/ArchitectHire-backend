"""notify_soon(): how the codebase asks for a notification, with or without Celery."""

from unittest.mock import patch

from django.test import override_settings

from apps.notifications.dispatch import notify_soon
from apps.notifications.tasks import deliver


def test_delivery_runs_in_process_by_default():
    """No worker is deployed, so `.delay()` would queue a task nothing ever consumes."""
    with (
        patch("apps.notifications.dispatch.post_commit_background") as background,
        patch("apps.notifications.dispatch.notify.delay") as delay,
    ):
        notify_soon(7, "milestone", "Approved", "body", {"engagement_id": 1})

    delay.assert_not_called()
    background.assert_called_once()
    args = background.call_args.args
    assert args[1] == "notify:milestone"
    assert args[2] is deliver
    assert args[3:] == (7, "milestone", "Approved", "body", {"engagement_id": 1})


@override_settings(NOTIFY_VIA_CELERY=True)
def test_celery_is_used_when_a_worker_really_exists():
    with (
        patch("apps.notifications.dispatch.notify.delay") as delay,
        patch("apps.notifications.dispatch.post_commit_background") as background,
    ):
        notify_soon(7, "lead", "Hired")

    delay.assert_called_once_with(7, "lead", "Hired", "", None)
    background.assert_not_called()


@override_settings(NOTIFY_VIA_CELERY=True)
def test_a_dead_broker_falls_back_to_in_process_delivery(caplog):
    with (
        patch("apps.notifications.dispatch.notify.delay", side_effect=OSError("no broker")),
        patch("apps.notifications.dispatch.post_commit_background") as background,
    ):
        notify_soon(7, "lead", "Hired")

    background.assert_called_once()
    assert "delivering lead in-process" in caplog.text
