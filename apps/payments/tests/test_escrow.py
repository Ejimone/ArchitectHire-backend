"""Escrow ledger tests — the money invariants.

Runs entirely on the MockGateway (no Stripe keys in tests): intents settle
instantly, Connect accounts verify instantly. The ledger math is identical
in production; only the gateway differs.
"""

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.accounts.factories import UserFactory
from apps.engagements.models import Engagement, Milestone
from apps.jurisdictions.models import State
from apps.payments.models import EscrowTransaction, FeePolicy, Payout, SubscriptionPlan
from apps.payments.services import escrow_summary, fund_engagement
from apps.projects.models import Project


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
        fee_percent=FeePolicy.current_percent(),
        status="contracted",
    )


def assert_ledger_balanced(engagement):
    for event_key in (
        EscrowTransaction.objects.filter(engagement=engagement)
        .values_list("event_key", flat=True)
        .distinct()
    ):
        rows = EscrowTransaction.objects.filter(event_key=event_key)
        debits = rows.filter(entry_type="debit").aggregate(s=Sum("amount"))["s"] or 0
        credits = rows.filter(entry_type="credit").aggregate(s=Sum("amount"))["s"] or 0
        assert debits == credits, f"Event {event_key} unbalanced: {debits} != {credits}"


@pytest.mark.django_db
class TestFunding:
    def test_fund_deposit_moves_into_escrow(self, engagement):
        record = fund_engagement(engagement, payer=engagement.client)
        assert record.status == "succeeded"
        assert record.amount == Decimal("5350.00")  # 25% of 21,400
        summary = escrow_summary(engagement)
        assert summary["in_escrow"] == "5350.00"
        engagement.refresh_from_db()
        assert engagement.status == "funded"
        assert_ledger_balanced(engagement)

    def test_funding_is_idempotent(self, engagement):
        fund_engagement(engagement)
        fund_engagement(engagement)
        assert escrow_summary(engagement)["in_escrow"] == "5350.00"

    def test_fund_via_api(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(f"/api/v1/payments/engagements/{engagement.pk}/fund/")
        assert response.status_code == 201
        assert response.json()["status"] == "succeeded"
        ledger = api_client.get(f"/api/v1/payments/engagements/{engagement.pk}/ledger/").json()
        assert ledger["in_escrow"] == "5350.00"

    def test_provider_cannot_fund(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.provider)
        assert (
            api_client.post(f"/api/v1/payments/engagements/{engagement.pk}/fund/").status_code
            == 403
        )


@pytest.mark.django_db
class TestMilestonePayment:
    """The client pays the architect directly — approving a milestone records
    that payment rather than releasing platform-held funds."""

    def _milestone(self, engagement, amount="2140.00"):
        return Milestone.objects.create(
            engagement=engagement,
            title="Schematic design",
            amount=Decimal(amount),
            status="in_review",
        )

    def test_approval_marks_milestone_paid(self, engagement):
        milestone = self._milestone(engagement)
        milestone.transition(Milestone.Status.DONE)
        from apps.payments.services import release_milestone

        assert release_milestone(milestone) == Decimal("2140.00")
        milestone.refresh_from_db()
        assert milestone.paid_at is not None

    def test_platform_takes_nothing(self, engagement):
        """The design's engagement page shows 'ArchitectHire fee $0'."""
        assert engagement.fee_percent == Decimal("0")
        assert engagement.platform_fee == Decimal("0.00")

    def test_no_ledger_entries_are_written(self, engagement):
        milestone = self._milestone(engagement)
        from apps.payments.services import release_milestone

        release_milestone(milestone)
        assert not EscrowTransaction.objects.filter(milestone=milestone).exists()
        assert not Payout.objects.filter(milestone=milestone).exists()

    def test_release_via_approve_endpoint(self, api_client, engagement):
        milestone = self._milestone(engagement)
        api_client.force_authenticate(user=engagement.client)
        response = api_client.post(f"/api/v1/milestones/{milestone.pk}/approve/")
        assert response.status_code == 200
        milestone.refresh_from_db()
        assert milestone.paid_at is not None

    def test_approval_is_idempotent(self, engagement):
        milestone = self._milestone(engagement)
        from apps.payments.services import release_milestone

        release_milestone(milestone)
        first = Milestone.objects.get(pk=milestone.pk).paid_at
        release_milestone(milestone)
        assert Milestone.objects.get(pk=milestone.pk).paid_at == first

    def test_zero_amount_milestone_is_not_payable(self, engagement):
        milestone = self._milestone(engagement, amount="0.00")
        from apps.payments.services import release_milestone

        assert release_milestone(milestone) is None
        milestone.refresh_from_db()
        assert milestone.paid_at is None

    def test_payment_summary(self, engagement):
        from apps.payments.services import engagement_payment_summary, release_milestone

        paid = self._milestone(engagement, amount="2140.00")
        self._milestone(engagement, amount="1000.00")
        release_milestone(paid)
        summary = engagement_payment_summary(engagement)
        assert summary["paid"] == "2140.00"
        assert summary["platform_fee"] == "0.00"
        assert summary["remaining"] == str(engagement.total - Decimal("2140.00"))


@pytest.mark.django_db
class TestSubscriptions:
    """Provider subscriptions are the platform's only revenue."""

    @pytest.fixture
    def plan(self, seeded):
        return SubscriptionPlan.objects.get(group="standard", key="practice")

    def test_plans_endpoint_is_public(self, api_client, seeded):
        body = api_client.get("/api/v1/payments/plans/").json()
        assert body["group"] == "standard"
        keys = [p["key"] for p in body["plans"]]
        assert keys == ["studio", "practice", "firm"]
        assert [p for p in body["plans"] if p["is_recommended"]][0]["key"] == "practice"

    def test_pricing_page_group_has_its_own_table(self, api_client, seeded):
        body = api_client.get("/api/v1/payments/plans/?group=pricing-page").json()
        firm = [p for p in body["plans"] if p["key"] == "firm"][0]
        assert firm["price_monthly"] == "299.00"  # per seat, differs from the standard table
        assert firm["per_unit"] == " / seat"

    def test_subscribe_and_cancel(self, api_client, engagement, plan):
        api_client.force_authenticate(user=engagement.provider)
        created = api_client.post(
            "/api/v1/payments/subscription/", {"plan": "practice"}, format="json"
        )
        assert created.status_code == 201
        assert created.json()["amount_due"] == "299.00"

        current = api_client.get("/api/v1/payments/subscription/").json()
        assert current["plan_name"] == "Practice"
        assert current["status"] == "active"

        canceled = api_client.delete("/api/v1/payments/subscription/")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

    def test_seats_multiply_the_charge(self, engagement, seeded):
        from apps.payments.services import subscribe

        firm = SubscriptionPlan.objects.get(group="pricing-page", key="firm")
        subscription = subscribe(engagement.provider, firm, seats=4)
        assert subscription.amount_due == Decimal("1196.00")  # 299 × 4 seats

    def test_yearly_billing_uses_the_yearly_rate(self, engagement, seeded):
        from apps.payments.services import subscribe

        plan = SubscriptionPlan.objects.get(group="standard", key="studio")
        subscription = subscribe(engagement.provider, plan, billing_period="yearly")
        assert subscription.amount_due == plan.price_yearly

    def test_unknown_plan_is_rejected(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.provider)
        response = api_client.post(
            "/api/v1/payments/subscription/", {"plan": "enterprise"}, format="json"
        )
        assert response.status_code == 400

    def test_bad_seats_and_period_are_rejected(self, api_client, engagement, plan):
        api_client.force_authenticate(user=engagement.provider)
        assert (
            api_client.post(
                "/api/v1/payments/subscription/", {"plan": "practice", "seats": 0}, format="json"
            ).status_code
            == 400
        )
        assert (
            api_client.post(
                "/api/v1/payments/subscription/",
                {"plan": "practice", "billing_period": "weekly"},
                format="json",
            ).status_code
            == 400
        )

    def test_no_subscription_states(self, api_client, engagement):
        api_client.force_authenticate(user=engagement.provider)
        assert api_client.get("/api/v1/payments/subscription/").json() == {"status": "none"}
        assert api_client.delete("/api/v1/payments/subscription/").status_code == 404

    def test_invoice_recording_is_idempotent(self, engagement, plan):
        from apps.payments.services import record_subscription_invoice, subscribe

        subscription = subscribe(engagement.provider, plan)
        record_subscription_invoice(subscription, amount=Decimal("299"), gateway_ref="in_1")
        record_subscription_invoice(subscription, amount=Decimal("299"), gateway_ref="in_1")
        assert subscription.invoices.count() == 1

    def test_webhook_updates_subscription_status(self, api_client, engagement, plan):
        import json

        from apps.payments.services import subscribe

        subscription = subscribe(engagement.provider, plan)
        event = {
            "id": "evt_sub_1",
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": subscription.gateway_ref}},
        }
        response = api_client.post(
            "/api/webhooks/stripe/", json.dumps(event), content_type="application/json"
        )
        assert response.status_code == 200
        subscription.refresh_from_db()
        assert subscription.status == "canceled"


@pytest.mark.django_db
class TestProviderBilling:
    def test_earnings_reports_booked_work_and_plan(self, api_client, engagement, seeded):
        from apps.payments.services import release_milestone, subscribe

        milestone = Milestone.objects.create(
            engagement=engagement,
            title="Schematic design",
            amount=Decimal("2140"),
            status="in_review",
        )
        release_milestone(milestone)
        subscribe(
            engagement.provider, SubscriptionPlan.objects.get(group="standard", key="practice")
        )

        api_client.force_authenticate(user=engagement.provider)
        body = api_client.get("/api/v1/payments/earnings/").json()
        assert body["booked_this_month"] == "2140.00"
        assert body["recent_contracts"][0]["title"] == "Schematic design"
        assert body["subscription"]["plan"] == "Practice"
        assert body["subscription"]["price"] == "299.00"


@pytest.mark.django_db
class TestWebhook:
    def test_dedup(self, api_client, engagement):
        import json

        record = fund_engagement(engagement)
        event = {
            "id": "evt_test_1",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": record.gateway_ref}},
        }
        for _ in range(2):
            response = api_client.post(
                "/api/webhooks/stripe/", json.dumps(event), content_type="application/json"
            )
            assert response.status_code == 200
        assert escrow_summary(engagement)["in_escrow"] == "5350.00"
