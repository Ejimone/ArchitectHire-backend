"""Money models.

Revenue comes from provider **subscriptions** (SubscriptionPlan / Subscription /
SubscriptionInvoice). Clients hire and pay their architect directly — the
platform takes nothing from a project.

The escrow ledger below (PaymentRecord, EscrowTransaction, PayoutAccount,
Payout) is **legacy**: it is no longer written to by the engagement flow, but
the tables are retained because they are append-only financial records. Its
invariant still holds for historical rows — every business event wrote balanced
entries (sum of debits == sum of credits).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.engagements.models import Engagement, Milestone
from apps.orders.models import Order


class SubscriptionPlan(TimeStampedModel):
    """A provider subscription tier — the platform's only revenue.

    `group` exists because the design presents two different tier tables: the
    recruiting pages and account onboarding show ceiling/coverage tiers
    ($79/$299/$699), while the dedicated pricing page shows a per-seat,
    feature-matrix set ($79/$149/$299) with a monthly/yearly toggle. Both are
    seeded so each page renders exactly as designed; the owner reconciles them
    in admin if they choose to.
    """

    class Group(models.TextChoices):
        STANDARD = "standard", "Recruiting pages & onboarding"
        PRICING_PAGE = "pricing-page", "Expert pricing page"

    group = models.CharField(max_length=20, choices=Group.choices, default=Group.STANDARD)
    key = models.SlugField(max_length=32)  # studio / practice / firm
    name = models.CharField(max_length=40)
    tagline = models.CharField(max_length=200, blank=True)
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2)
    price_yearly = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Per month, billed annually",
    )
    per_unit = models.CharField(max_length=24, blank=True, help_text="e.g. ' / seat'")
    project_ceiling = models.CharField(max_length=60, blank=True)
    metro_coverage = models.CharField(max_length=60, blank=True)
    pursuit_limit = models.CharField(max_length=60, blank=True)
    fits = models.CharField(max_length=160, blank=True)
    points = models.JSONField(default=list, blank=True)
    cta_label = models.CharField(max_length=48, blank=True)
    is_recommended = models.BooleanField(default=False)
    gateway_price_id = models.CharField(max_length=120, blank=True, help_text="Stripe price id")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["group", "sort_order"]
        unique_together = [("group", "key")]

    def __str__(self):
        return f"{self.name} · ${self.price_monthly}/mo ({self.group})"


class Subscription(TimeStampedModel):
    """A provider's active plan."""

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    class Period(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    provider = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscribers")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    billing_period = models.CharField(max_length=8, choices=Period.choices, default=Period.MONTHLY)
    seats = models.PositiveSmallIntegerField(default=1)
    current_period_end = models.DateTimeField(null=True, blank=True)
    gateway_ref = models.CharField(max_length=120, blank=True, db_index=True)
    card_label = models.CharField(max_length=40, blank=True)  # design: "Visa ••4021"

    def __str__(self):
        return f"{self.provider.email} · {self.plan.name} ({self.status})"

    @property
    def amount_due(self) -> Decimal:
        """What this provider is billed per period, including seats."""
        unit = self.plan.price_monthly
        if self.billing_period == self.Period.YEARLY and self.plan.price_yearly is not None:
            unit = self.plan.price_yearly
        return (unit * self.seats).quantize(Decimal("0.01"))


class SubscriptionInvoice(TimeStampedModel):
    """One billing charge against a subscription (design: 'Billing' panel)."""

    class Status(models.TextChoices):
        PAID = "paid", "Paid"
        OPEN = "open", "Open"
        FAILED = "failed", "Failed"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="invoices"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PAID)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    gateway_ref = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"${self.amount} · {self.subscription.provider.email} ({self.status})"


class FeePolicy(TimeStampedModel):
    """Legacy per-project platform fee. The platform now takes 0% of a project —
    clients pay their architect directly — so this defaults to zero. Retained
    because existing engagements snapshotted a percent at creation time.
    """

    percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "fee policies"

    def __str__(self):
        return f"{self.percent}% {'(active)' if self.is_active else ''}"

    @classmethod
    def current_percent(cls) -> Decimal:
        policy = cls.objects.filter(is_active=True).first()
        return policy.percent if policy else Decimal("0")


class PaymentRecord(TimeStampedModel):
    """A gateway charge (escrow deposit or order payment)."""

    class Kind(models.TextChoices):
        ESCROW_DEPOSIT = "escrow_deposit", "Escrow deposit"
        ORDER_PAYMENT = "order_payment", "Order payment"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    engagement = models.ForeignKey(
        Engagement, on_delete=models.CASCADE, null=True, blank=True, related_name="payments"
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, null=True, blank=True, related_name="payments"
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="usd")
    gateway_ref = models.CharField(max_length=120, blank=True, db_index=True)  # PaymentIntent id
    client_secret = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    idempotency_key = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} ${self.amount} · {self.status}"


class EscrowTransaction(TimeStampedModel):
    """Append-only double-entry ledger row."""

    class Account(models.TextChoices):
        CLIENT_FUNDS = "client_funds", "Client funds"
        ESCROW = "escrow", "Escrow"
        PLATFORM_FEES = "platform_fees", "Platform fees"
        PROVIDER_PAYABLE = "provider_payable", "Provider payable"
        PAID_OUT = "paid_out", "Paid out"

    class Entry(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    engagement = models.ForeignKey(
        Engagement, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger"
    )
    order = models.ForeignKey(
        Order, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger"
    )
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger"
    )
    account = models.CharField(max_length=20, choices=Account.choices)
    entry_type = models.CharField(max_length=6, choices=Entry.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="usd")
    external_ref = models.CharField(max_length=120, blank=True)
    event_key = models.CharField(max_length=140, db_index=True)  # groups one balanced event
    memo = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.entry_type} {self.account} ${self.amount}"


class PayoutAccount(TimeStampedModel):
    """Provider's Connect account (design: 'Chase Business ••4021 — Verified')."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending onboarding"
        VERIFIED = "verified", "Verified"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_account"
    )
    gateway_account_id = models.CharField(max_length=120, blank=True)
    bank_label = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    def __str__(self):
        return f"{self.user.email} · {self.bank_label or self.status}"


class Payout(TimeStampedModel):
    """A transfer of released funds to a provider (design: ~2 business days)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payouts"
    )
    engagement = models.ForeignKey(
        Engagement, on_delete=models.SET_NULL, null=True, blank=True, related_name="payouts"
    )
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="payouts"
    )
    title = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    gateway_transfer_ref = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"${self.amount} → {self.provider.email} ({self.status})"


class WebhookEvent(TimeStampedModel):
    """Gateway webhook dedup + audit."""

    gateway_id = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} · {self.gateway_id}"
