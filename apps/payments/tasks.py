"""Scheduled money jobs."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="apps.payments.tasks.sweep_pending_payouts")
def sweep_pending_payouts():
    """Retry pending payouts whose providers now have a verified payout account."""
    from django.utils import timezone

    from apps.payments.gateway import get_gateway
    from apps.payments.models import EscrowTransaction, Payout, PayoutAccount
    from apps.payments.services import _write

    Account = EscrowTransaction.Account
    Entry = EscrowTransaction.Entry
    paid = 0
    for payout in Payout.objects.filter(status=Payout.Status.PENDING).select_related("provider"):
        account = PayoutAccount.objects.filter(
            user=payout.provider, status=PayoutAccount.Status.VERIFIED
        ).first()
        if not (account and account.gateway_account_id):
            continue
        transfer = get_gateway().create_transfer(
            amount=payout.amount,
            destination=account.gateway_account_id,
            metadata={"payout_id": str(payout.pk)},
        )
        payout.gateway_transfer_ref = transfer["id"]
        payout.status = Payout.Status.PAID
        payout.paid_at = timezone.now()
        payout.save(update_fields=["gateway_transfer_ref", "status", "paid_at"])
        _write(
            f"payout-{payout.pk}",
            [
                (
                    Account.PROVIDER_PAYABLE,
                    Entry.DEBIT,
                    payout.amount,
                    {"engagement": payout.engagement, "external_ref": transfer["id"]},
                ),
                (
                    Account.PAID_OUT,
                    Entry.CREDIT,
                    payout.amount,
                    {"engagement": payout.engagement, "external_ref": transfer["id"]},
                ),
            ],
        )
        paid += 1
    return f"paid {paid}"


@shared_task(name="apps.payments.tasks.cleanup_stale_data")
def cleanup_stale_data():
    """Prune anonymous estimates older than 90 days and read notifications older than 180."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.models import Notification
    from apps.projects.models import Estimate

    now = timezone.now()
    estimates, _ = (
        Estimate.objects.filter(user__isnull=True, created_at__lt=now - timedelta(days=90))
        .exclude(project__isnull=False)
        .delete()
    )
    notifications, _ = Notification.objects.filter(
        read_at__isnull=False, created_at__lt=now - timedelta(days=180)
    ).delete()
    return f"estimates={estimates} notifications={notifications}"
