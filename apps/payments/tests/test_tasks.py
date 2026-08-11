"""Scheduled money jobs: payout sweeping and stale-data pruning."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.factories import UserFactory
from apps.jurisdictions.models import State
from apps.notifications.models import Notification
from apps.payments.models import EscrowTransaction, Payout, PayoutAccount
from apps.payments.tasks import cleanup_stale_data, sweep_pending_payouts
from apps.projects.models import Estimate


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions")


@pytest.mark.django_db
class TestSweepPendingPayouts:
    def test_pays_out_once_the_account_is_verified(self):
        provider = UserFactory(role="architect")
        PayoutAccount.objects.create(
            user=provider,
            gateway_account_id="acct_sweep_1",
            status=PayoutAccount.Status.VERIFIED,
        )
        payout = Payout.objects.create(
            provider=provider, amount=Decimal("2140.00"), title="Schematic design"
        )

        assert sweep_pending_payouts() == "paid 1"

        payout.refresh_from_db()
        assert payout.status == Payout.Status.PAID
        assert payout.gateway_transfer_ref.startswith("tr_mock_")
        assert payout.paid_at is not None

        rows = EscrowTransaction.objects.filter(event_key=f"payout-{payout.pk}")
        assert {(r.account, r.entry_type) for r in rows} == {
            ("provider_payable", "debit"),
            ("paid_out", "credit"),
        }

    def test_skips_providers_without_a_verified_account(self):
        provider = UserFactory(role="architect")
        payout = Payout.objects.create(provider=provider, amount=Decimal("500.00"))
        # An account that exists but is still pending onboarding is not enough.
        PayoutAccount.objects.create(user=provider, status=PayoutAccount.Status.PENDING)

        assert sweep_pending_payouts() == "paid 0"
        payout.refresh_from_db()
        assert payout.status == Payout.Status.PENDING


@pytest.mark.django_db
class TestCleanupStaleData:
    def test_prunes_old_anonymous_estimates_and_read_notifications(self, seeded):
        state = State.objects.get(code="CA")
        amounts = dict.fromkeys(
            ["rate", "base", "addon_total", "multiplier", "total", "low", "high"], Decimal("1")
        )
        old = Estimate.objects.create(
            project_type="Residential",
            scope="ADU",
            sqft=640,
            state=state,
            timeline="Standard (10–12 wks)",
            addons={},
            **amounts,
        )
        fresh = Estimate.objects.create(
            project_type="Residential",
            scope="ADU",
            sqft=640,
            state=state,
            timeline="Standard (10–12 wks)",
            addons={},
            **amounts,
        )
        Estimate.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=120))

        user = UserFactory()
        stale_note = Notification.objects.create(
            user=user, kind="system", title="Old", read_at=timezone.now()
        )
        unread_note = Notification.objects.create(user=user, kind="system", title="Unread")
        Notification.objects.filter(pk=stale_note.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )

        result = cleanup_stale_data()

        assert result.startswith("estimates=")
        assert not Estimate.objects.filter(pk=old.pk).exists()
        assert Estimate.objects.filter(pk=fresh.pk).exists()
        assert not Notification.objects.filter(pk=stale_note.pk).exists()
        assert Notification.objects.filter(pk=unread_note.pk).exists()
