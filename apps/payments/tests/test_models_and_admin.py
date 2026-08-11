"""Money model strings and the append-only guards on their admin pages."""

from decimal import Decimal

import pytest
from django.contrib.admin.sites import site

from apps.accounts.models import User
from apps.payments import models as payments
from apps.payments.admin import (
    EscrowTransactionAdmin,
    PaymentRecordAdmin,
    WebhookEventAdmin,
)

PROVIDER = User(email="pro@example.com")
PLAN = payments.SubscriptionPlan(name="Practice", price_monthly=Decimal("299.00"), group="standard")


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (PLAN, "Practice · $299.00/mo (standard)"),
        (
            payments.Subscription(provider=PROVIDER, plan=PLAN, status="active"),
            "pro@example.com · Practice (active)",
        ),
        (
            payments.SubscriptionInvoice(
                subscription=payments.Subscription(provider=PROVIDER, plan=PLAN),
                amount=Decimal("299.00"),
                status="paid",
            ),
            "$299.00 · pro@example.com (paid)",
        ),
        (payments.FeePolicy(percent=Decimal("0.00"), is_active=True), "0.00% (active)"),
        (payments.FeePolicy(percent=Decimal("10.00"), is_active=False), "10.00% "),
        (
            payments.PaymentRecord(
                kind="escrow_deposit", amount=Decimal("5350.00"), status="succeeded"
            ),
            "Escrow deposit $5350.00 · succeeded",
        ),
        (
            payments.EscrowTransaction(
                entry_type="debit", account="escrow", amount=Decimal("5350.00")
            ),
            "debit escrow $5350.00",
        ),
        (
            payments.PayoutAccount(user=PROVIDER, bank_label="Chase Business ••4021"),
            "pro@example.com · Chase Business ••4021",
        ),
        (
            payments.PayoutAccount(user=PROVIDER, bank_label="", status="pending"),
            "pro@example.com · pending",
        ),
        (
            payments.Payout(provider=PROVIDER, amount=Decimal("2140.00"), status="paid"),
            "$2140.00 → pro@example.com (paid)",
        ),
        (
            payments.WebhookEvent(gateway_id="evt_1", event_type="payment_intent.succeeded"),
            "payment_intent.succeeded · evt_1",
        ),
    ],
)
def test_str(obj, expected):
    assert str(obj) == expected


def test_financial_records_are_read_only_in_admin():
    assert PaymentRecordAdmin(payments.PaymentRecord, site).has_add_permission(None) is False
    assert WebhookEventAdmin(payments.WebhookEvent, site).has_add_permission(None) is False

    ledger_admin = EscrowTransactionAdmin(payments.EscrowTransaction, site)
    assert ledger_admin.has_add_permission(None) is False
    assert ledger_admin.has_delete_permission(None) is False
