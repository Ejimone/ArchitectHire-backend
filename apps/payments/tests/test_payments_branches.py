"""Remaining payment paths: ledger guards, order payments, payout accounts,
webhook rejections and the funding/subscription request validation."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.engagements.models import Engagement
from apps.jurisdictions.models import State
from apps.orders.models import Order
from apps.payments.models import (
    EscrowTransaction,
    PaymentRecord,
    PayoutAccount,
    SubscriptionPlan,
)
from apps.payments.services import (
    _write,
    confirm_payment,
    ensure_payout_account,
    subscribe,
)
from apps.projects.models import Project

Account = EscrowTransaction.Account
Entry = EscrowTransaction.Entry


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog,payments")


@pytest.fixture
def engagement(seeded, db):
    client = UserFactory(role="client")
    architect = UserFactory(role="architect")
    project = Project.objects.create(
        owner=client,
        title="Addition · California",
        project_type="Residential",
        scope="Addition",
        sqft=2400,
        state=State.objects.get(code="CA"),
        status="underway",
        architect=architect,
    )
    return Engagement.objects.create(
        project=project,
        client=client,
        provider=architect,
        kind="dynamic_fixed_quote",
        total=Decimal("21400"),
        status="contracted",
    )


@pytest.mark.django_db
class TestLedgerWrites:
    def test_unbalanced_event_is_rejected(self):
        with pytest.raises(ValidationError, match="Unbalanced ledger event"):
            _write("qa-unbalanced", [(Account.ESCROW, Entry.CREDIT, Decimal("10"), {})])

    def test_writing_the_same_event_twice_is_a_no_op(self):
        rows = [
            (Account.CLIENT_FUNDS, Entry.DEBIT, Decimal("10"), {}),
            (Account.ESCROW, Entry.CREDIT, Decimal("10"), {}),
        ]
        _write("qa-idempotent", rows)
        _write("qa-idempotent", rows)
        assert EscrowTransaction.objects.filter(event_key="qa-idempotent").count() == 2


@pytest.mark.django_db
class TestOrderPayments:
    def test_confirming_an_order_payment_funds_the_order(self):
        order = Order.objects.create(
            kind="render",
            config={"deliverable": "Interior still"},
            customer_email="buyer@example.com",
            subtotal=Decimal("420.00"),
            total=Decimal("420.00"),
        )
        PaymentRecord.objects.create(
            kind=PaymentRecord.Kind.ORDER_PAYMENT,
            order=order,
            amount=Decimal("420.00"),
            gateway_ref="pi_order_qa",
            idempotency_key="qa-order-payment",
        )

        record = confirm_payment("pi_order_qa")

        assert record.status == PaymentRecord.Status.SUCCEEDED
        order.refresh_from_db()
        assert order.status == "funded"
        rows = EscrowTransaction.objects.filter(event_key=f"order-fund-{record.pk}")
        assert {(r.account, r.entry_type) for r in rows} == {
            ("client_funds", "debit"),
            ("escrow", "credit"),
        }


@pytest.mark.django_db
class TestPayoutAccounts:
    def test_ensure_creates_a_verified_mock_account_and_link(self):
        provider = UserFactory(role="architect")
        account, link = ensure_payout_account(provider)
        assert account.status == PayoutAccount.Status.VERIFIED
        assert account.gateway_account_id.startswith("acct_mock_")
        assert link.endswith("/pro?connect=done")

        # Second call reuses the stored account rather than creating another.
        again, _ = ensure_payout_account(provider)
        assert again.pk == account.pk

    def test_endpoint_reports_none_then_the_created_account(self, api_client):
        provider = UserFactory(role="architect")
        api_client.force_authenticate(user=provider)

        assert api_client.get("/api/v1/payments/payout-account/").json() == {"status": "none"}

        created = api_client.post("/api/v1/payments/payout-account/").json()
        assert created["status"] == "verified"
        assert created["onboarding_url"].endswith("/pro?connect=done")

        current = api_client.get("/api/v1/payments/payout-account/").json()
        assert current["status"] == "verified"
        assert current["bank_label"] == "Mock Bank ••0000"


@pytest.mark.django_db
class TestSubscriptionPeriodEnd:
    def test_epoch_period_end_from_the_gateway_is_converted(self, engagement, seeded):
        plan = SubscriptionPlan.objects.get(group="standard", key="practice")
        stub = SimpleNamespace(
            create_subscription=lambda **kwargs: {
                "id": "sub_qa",
                "status": "active",
                "current_period_end": 1767225600,
                "card_label": "Visa ••4021",
            }
        )
        with patch("apps.payments.services.get_gateway", return_value=stub):
            subscription = subscribe(engagement.provider, plan)
        assert subscription.current_period_end == datetime.fromtimestamp(1767225600, tz=UTC)
        assert subscription.card_label == "Visa ••4021"


@pytest.mark.django_db
class TestFundingRequestValidation:
    def test_custom_amount_is_honoured(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/payments/engagements/{engagement.pk}/fund/",
            {"amount": "1000.00"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["amount"] == "1000.00"

    @pytest.mark.parametrize("amount", ["not-a-number", "-5"])
    def test_bad_amounts_are_rejected(self, api_client, engagement, amount):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(
            f"/api/v1/payments/engagements/{engagement.pk}/fund/",
            {"amount": amount},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Bad amount."


@pytest.mark.django_db
class TestWebhookRejections:
    def test_unverifiable_payload_is_rejected(self, api_client):
        response = api_client.post(
            "/api/webhooks/stripe/", "not json at all", content_type="application/json"
        )
        assert response.status_code == 400

    def test_event_without_an_id_is_rejected(self, api_client):
        response = api_client.post(
            "/api/webhooks/stripe/", json.dumps({}), content_type="application/json"
        )
        assert response.status_code == 400

    def test_account_updated_verifies_the_payout_account(self, api_client):
        provider = UserFactory(role="architect")
        account = PayoutAccount.objects.create(
            user=provider, gateway_account_id="acct_hook_qa", status=PayoutAccount.Status.PENDING
        )
        event = {
            "id": "evt_account_qa",
            "type": "account.updated",
            "data": {"object": {"id": "acct_hook_qa", "payouts_enabled": True}},
        }
        response = api_client.post(
            "/api/webhooks/stripe/", json.dumps(event), content_type="application/json"
        )
        assert response.status_code == 200
        account.refresh_from_db()
        assert account.status == PayoutAccount.Status.VERIFIED


@pytest.mark.django_db
class TestSubscriptionRequestValidation:
    def test_non_numeric_seats_are_rejected(self, api_client, engagement, seeded):
        api_client.force_authenticate(user=engagement.provider)
        response = api_client.post(
            "/api/v1/payments/subscription/",
            {"plan": "practice", "seats": "lots"},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Seats must be a number."
