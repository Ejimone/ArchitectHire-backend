"""The working contract between client and provider.

Design (Engagement.dc.html): two contract types — dynamic fixed quote (flagship,
25% escrow deposit) and hourly (initial escrow of 20 hours). Milestones release
escrow on client approval; change requests and re-quote flags need the client;
time entries keep hourly work transparent; deliverables live on private storage.
The platform fee percent is SNAPSHOTTED at creation (design shows conflicting
rates precisely because it must be config, not code).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import OrderableModel, TimeStampedModel
from apps.core.storages import private_storage
from apps.projects.models import Project

INITIAL_ESCROW_HOURS = 20  # design: "Initial escrow (20 hrs)"
FIXED_DEPOSIT_PCT = Decimal("0.25")  # design: "Deposit into escrow (25%)"


class Engagement(TimeStampedModel):
    class Kind(models.TextChoices):
        FIXED = "dynamic_fixed_quote", "Dynamic fixed quote"
        HOURLY = "hourly", "Hourly"

    class Status(models.TextChoices):
        SCOPING = "scoping", "Scoping"
        CONTRACTED = "contracted", "Contracted"
        FUNDED = "funded", "Escrow funded · underway"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="engagement")
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_engagements"
    )
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="provider_engagements"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCOPING)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project} · {self.get_kind_display()}"

    def clean(self):
        if self.kind == self.Kind.FIXED and not self.total:
            raise ValidationError({"total": "Fixed-quote engagements need a total."})
        if self.kind == self.Kind.HOURLY and not self.hourly_rate:
            raise ValidationError({"hourly_rate": "Hourly engagements need a rate."})

    @property
    def deposit_amount(self) -> Decimal:
        if self.kind == self.Kind.FIXED:
            return (self.total * FIXED_DEPOSIT_PCT).quantize(Decimal("0.01"))
        return (self.hourly_rate * INITIAL_ESCROW_HOURS).quantize(Decimal("0.01"))

    @property
    def platform_fee(self) -> Decimal:
        base = self.total if self.kind == self.Kind.FIXED else self.deposit_amount
        return (base * self.fee_percent / 100).quantize(Decimal("0.01"))

    def validate_milestones_sum(self):
        """Fixed-quote milestones must sum exactly to the contract total (the design's
        demo data violates this — real engagements must not)."""
        if self.kind != self.Kind.FIXED:
            return
        total = sum((m.amount or Decimal("0")) for m in self.milestones.all())
        if total != self.total:
            raise ValidationError(
                f"Milestone amounts (${total}) must sum to the contract total (${self.total})."
            )


class Milestone(OrderableModel, TimeStampedModel):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        IN_REVIEW = "in_review", "In review"
        REVISING = "revising", "Revising"
        DONE = "done", "Done"

    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=120)  # Kickoff / Schematic design / ...
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPCOMING)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return f"{self.title} (${self.amount or 0})"

    TRANSITIONS = {
        Status.UPCOMING: {Status.IN_REVIEW},
        Status.IN_REVIEW: {Status.DONE, Status.REVISING},
        Status.REVISING: {Status.IN_REVIEW},
        Status.DONE: set(),
    }

    def transition(self, new_status):
        if new_status not in self.TRANSITIONS[self.Status(self.status)]:
            raise ValidationError(f"Cannot move milestone from {self.status} to {new_status}.")
        self.status = new_status
        if new_status == self.Status.DONE:
            self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_at"])


class ChangeRequest(TimeStampedModel):
    """Client 'request changes' on a milestone (design: quick chips + note + markup)."""

    CATEGORY_CHOICES = [
        "Adjust the floor plan",
        "Window / door changes",
        "Structural concern",
        "Something else",
    ]

    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name="change_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    categories = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True)
    markup = models.FileField(
        upload_to="engagements/markups/%Y/%m/", storage=private_storage, blank=True
    )

    class Meta:
        ordering = ["-created_at"]


class RequoteFlag(TimeStampedModel):
    """Provider-raised scope/price change; the client must approve (design: RE-QUOTE FLAG)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending client approval"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="requotes")
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    old_total = models.DecimalField(max_digits=12, decimal_places=2)
    new_total = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def resolve(self, approve: bool):
        if self.status != self.Status.PENDING:
            raise ValidationError("Re-quote already resolved.")
        self.status = self.Status.APPROVED if approve else self.Status.DECLINED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at"])
        if approve:
            self.engagement.total = self.new_total
            self.engagement.save(update_fields=["total"])


class TimeEntry(TimeStampedModel):
    """Hourly transparency — tracked, on-platform, client-visible."""

    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="time_entries")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name_plural = "time entries"


class Deliverable(TimeStampedModel):
    """Drawings & files (design: 'A-201 Proposed plan.pdf · 2.4 MB · Aug 8 · NEW')."""

    engagement = models.ForeignKey(Engagement, on_delete=models.CASCADE, related_name="deliverables")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    file = models.FileField(upload_to="engagements/deliverables/%Y/%m/", storage=private_storage)
    name = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(default=0)
    stamped = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
