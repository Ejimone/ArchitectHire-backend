import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Order(TimeStampedModel):
    """A productized order (render or drafting) with a frozen price snapshot."""

    class Kind(models.TextChoices):
        RENDER = "render", "3D visualization"
        DRAFTING = "drafting", "CAD drafting"

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        FUNDED = "funded", "Escrow funded"
        IN_PROGRESS = "in_progress", "In progress"
        DELIVERED = "delivered", "First draft delivered"
        APPROVED = "approved", "Approved"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    config = (
        models.JSONField()
    )  # deliverable/tier/qty | service/size/stamp + rush + "what you have"
    customer_name = models.CharField(max_length=80, blank=True)
    customer_email = models.EmailField()
    notes = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    stamp_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rush_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    expert = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expert_orders",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.customer_email} · ${self.total}"


class OrderFile(TimeStampedModel):
    """Customer-supplied reference/source files."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="orders/reference/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.original_name or self.file.name
