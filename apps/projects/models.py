import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.jurisdictions.models import State

RESIDENTIAL_SCOPES = ["Renovation", "Addition", "New custom home", "ADU", "Kitchen / bath"]
COMMERCIAL_SCOPES = [
    "Tenant improvement",
    "Office fit-out",
    "Retail build-out",
    "Restaurant",
    "Change of use",
]
TIMELINES = ["Rush (6–8 wks)", "Standard (10–12 wks)", "Flexible (14+ wks)"]


class Estimate(TimeStampedModel):
    """Frozen snapshot of an instant estimate (pre-signup funnel; claimable at signup)."""

    class ProjectKind(models.TextChoices):
        RESIDENTIAL = "Residential", "Residential"
        COMMERCIAL = "Commercial", "Commercial"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimates",
    )

    project_type = models.CharField(max_length=16, choices=ProjectKind.choices)
    scope = models.CharField(max_length=40)
    sqft = models.PositiveIntegerField()
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="estimates")
    timeline = models.CharField(max_length=32)
    addons = models.JSONField(default=dict)  # {"structural": true, ...}

    # Snapshot of engine output at creation time
    rate = models.DecimalField(max_digits=8, decimal_places=2)
    base = models.DecimalField(max_digits=12, decimal_places=2)
    addon_total = models.DecimalField(max_digits=12, decimal_places=2)
    multiplier = models.DecimalField(max_digits=6, decimal_places=3)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    low = models.DecimalField(max_digits=12, decimal_places=2)
    high = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.scope} · {self.sqft} sf · {self.state.code} (${self.low}–${self.high})"
