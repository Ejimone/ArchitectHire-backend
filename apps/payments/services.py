"""Payment business logic.

The platform takes nothing from a project — the client pays their architect
directly — so approving a milestone *records* payment rather than releasing
escrow. Subscription helpers below are the platform's actual revenue path.

The `_write` / `account_balance` ledger helpers remain for the legacy escrow
tables, which are append-only and still queried for historical engagements.
"""

from datetime import UTC
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.engagements.models import Engagement, Milestone

from .gateway import get_gateway
from .models import (
    EscrowTransaction,
    PaymentRecord,
    PayoutAccount,
    Subscription,
    SubscriptionInvoice,
)

Account = EscrowTransaction.Account
Entry = EscrowTransaction.Entry


def _write(event_key, rows):
    """Write one balanced ledger event. rows: [(account, entry, amount, kwargs)]"""
    debits = sum(amount for _, entry, amount, _ in rows if entry == Entry.DEBIT)
    credits = sum(amount for _, entry, amount, _ in rows if entry == Entry.CREDIT)
    if debits != credits:
        raise ValidationError(f"Unbalanced ledger event {event_key}: {debits} != {credits}")
    if EscrowTransaction.objects.filter(event_key=event_key).exists():
        return  # idempotent
    for account, entry, amount, kwargs in rows:
        EscrowTransaction.objects.create(
            account=account, entry_type=entry, amount=amount, event_key=event_key, **kwargs
        )


def account_balance(engagement: Engagement, account: str) -> Decimal:
    rows = EscrowTransaction.objects.filter(engagement=engagement, account=account)
    credits = rows.filter(entry_type=Entry.CREDIT).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    debits = rows.filter(entry_type=Entry.DEBIT).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return credits - debits


def escrow_summary(engagement: Engagement) -> dict:
    released = EscrowTransaction.objects.filter(
        engagement=engagement, account=Account.PROVIDER_PAYABLE, entry_type=Entry.CREDIT
    ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    paid_out = account_balance(engagement, Account.PAID_OUT)
    return {
        "in_escrow": str(account_balance(engagement, Account.ESCROW)),
        "released": str(released),
        "platform_fees": str(account_balance(engagement, Account.PLATFORM_FEES)),
        "provider_payable": str(account_balance(engagement, Account.PROVIDER_PAYABLE)),
        "paid_out": str(paid_out),
    }


@transaction.atomic
def fund_engagement(
    engagement: Engagement, *, amount: Decimal | None = None, payer=None
) -> PaymentRecord:
    """Create the escrow-funding charge (default: the design's deposit amount)."""
    amount = amount or engagement.deposit_amount
    key = f"fund-{engagement.pk}-{amount}"
    existing = PaymentRecord.objects.filter(idempotency_key=key).first()
    if existing and existing.status != PaymentRecord.Status.FAILED:
        return existing

    gateway = get_gateway()
    intent = gateway.create_payment_intent(
        amount=amount,
        currency="usd",
        metadata={"engagement_id": str(engagement.pk), "kind": "escrow_deposit"},
    )
    record = PaymentRecord.objects.create(
        kind=PaymentRecord.Kind.ESCROW_DEPOSIT,
        engagement=engagement,
        payer=payer,
        amount=amount,
        gateway_ref=intent["id"],
        client_secret=intent.get("client_secret", ""),
        idempotency_key=key,
    )
    if intent.get("status") == "succeeded":  # mock gateway settles instantly
        confirm_payment(record.gateway_ref)
        record.refresh_from_db()
    return record


@transaction.atomic
def confirm_payment(gateway_ref: str):
    """Payment settled (webhook or mock): move funds into escrow."""
    record = PaymentRecord.objects.select_for_update().get(gateway_ref=gateway_ref)
    if record.status == PaymentRecord.Status.SUCCEEDED:
        return record
    record.status = PaymentRecord.Status.SUCCEEDED
    record.save(update_fields=["status"])

    if record.kind == PaymentRecord.Kind.ESCROW_DEPOSIT and record.engagement:
        engagement = record.engagement
        _write(
            f"fund-{record.pk}",
            [
                (
                    Account.CLIENT_FUNDS,
                    Entry.DEBIT,
                    record.amount,
                    {
                        "engagement": engagement,
                        "external_ref": gateway_ref,
                        "memo": "Escrow deposit",
                    },
                ),
                (
                    Account.ESCROW,
                    Entry.CREDIT,
                    record.amount,
                    {
                        "engagement": engagement,
                        "external_ref": gateway_ref,
                        "memo": "Escrow deposit",
                    },
                ),
            ],
        )
        if engagement.status == Engagement.Status.CONTRACTED:
            engagement.status = Engagement.Status.FUNDED
            engagement.save(update_fields=["status"])
            project = engagement.project
            project.progress_pct = max(project.progress_pct, 20)
            project.next_action = "Review the first milestone"
            project.save(update_fields=["progress_pct", "next_action"])
    elif record.kind == PaymentRecord.Kind.ORDER_PAYMENT and record.order:
        order = record.order
        order.status = "funded"
        order.save(update_fields=["status"])
        _write(
            f"order-fund-{record.pk}",
            [
                (
                    Account.CLIENT_FUNDS,
                    Entry.DEBIT,
                    record.amount,
                    {"order": order, "external_ref": gateway_ref},
                ),
                (
                    Account.ESCROW,
                    Entry.CREDIT,
                    record.amount,
                    {"order": order, "external_ref": gateway_ref},
                ),
            ],
        )
    return record


@transaction.atomic
def release_milestone(milestone: Milestone):
    """Client approved the milestone — record that its amount is now payable to
    the architect, who the client pays directly. No platform funds move.

    Returns the milestone's payable amount, or None when it carries no amount
    (hourly engagements bill through time entries instead).
    """
    amount = milestone.amount or Decimal("0")
    if amount <= 0:
        return None
    if milestone.paid_at is None:
        milestone.paid_at = timezone.now()
        milestone.save(update_fields=["paid_at"])
    return amount


def engagement_payment_summary(engagement: Engagement) -> dict:
    """What the design's engagement dashboard shows: REMAINING vs PAID TO <provider>."""
    milestones = engagement.milestones.all()
    paid = sum((m.amount or Decimal("0")) for m in milestones if m.paid_at)
    contracted = engagement.total or Decimal("0")
    return {
        "contracted": str(contracted),
        "paid": str(paid),
        "remaining": str(max(contracted - paid, Decimal("0"))),
        "platform_fee": str(engagement.platform_fee),
    }


def ensure_payout_account(user) -> tuple[PayoutAccount, str]:
    """Create/fetch the provider's Connect account and an onboarding link."""
    from django.conf import settings

    account, _created = PayoutAccount.objects.get_or_create(user=user)
    gateway = get_gateway()
    if not account.gateway_account_id:
        created = gateway.create_connect_account(email=user.email)
        account.gateway_account_id = created["id"]
        if created.get("status") == "verified":  # mock mode
            account.status = PayoutAccount.Status.VERIFIED
            account.bank_label = "Mock Bank ••0000"
        account.save()
    link = gateway.create_account_link(
        account_id=account.gateway_account_id,
        refresh_url=f"{settings.FRONTEND_URL}/pro?connect=refresh",
        return_url=f"{settings.FRONTEND_URL}/pro?connect=done",
    )
    return account, link


# --- Subscriptions (the platform's revenue) ---------------------------------


def subscribe(provider, plan, *, billing_period="monthly", seats=1) -> "Subscription":
    """Start or switch a provider's subscription via the gateway."""
    from datetime import datetime

    gateway = get_gateway()
    result = gateway.create_subscription(
        customer_email=provider.email, price_id=plan.gateway_price_id, seats=seats
    )
    period_end = result.get("current_period_end")
    if isinstance(period_end, int):
        period_end = datetime.fromtimestamp(period_end, tz=UTC)

    subscription, _created = Subscription.objects.update_or_create(
        provider=provider,
        defaults={
            "plan": plan,
            "billing_period": billing_period,
            "seats": seats,
            "status": result.get("status", Subscription.Status.ACTIVE),
            "gateway_ref": result["id"],
            "current_period_end": period_end,
            "card_label": result.get("card_label", ""),
        },
    )
    return subscription


def cancel_subscription(subscription: "Subscription") -> "Subscription":
    if subscription.gateway_ref:
        get_gateway().cancel_subscription(subscription_ref=subscription.gateway_ref)
    subscription.status = Subscription.Status.CANCELED
    subscription.save(update_fields=["status"])
    return subscription


def record_subscription_invoice(subscription, *, amount, gateway_ref="", status="paid"):
    """Idempotent billing-history row (design: the provider's Billing panel)."""
    invoice, _created = SubscriptionInvoice.objects.get_or_create(
        subscription=subscription,
        gateway_ref=gateway_ref,
        defaults={"amount": amount, "status": status},
    )
    return invoice
