import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

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


class Project(TimeStampedModel):
    """A client project: claimed estimate → matching → engagement → completion."""

    class Status(models.TextChoices):
        CHOOSING_ARCHITECT = "choosing_architect", "Choosing architect"
        UNDERWAY = "underway", "Underway"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects"
    )
    estimate = models.OneToOneField(
        Estimate, on_delete=models.SET_NULL, null=True, blank=True, related_name="project"
    )
    title = models.CharField(max_length=120)  # "Addition · Oakland, CA"
    project_type = models.CharField(max_length=16)  # Residential / Commercial
    project_type_ref = models.ForeignKey(
        "catalog.ProjectType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )
    scope = models.CharField(max_length=40)
    sqft = models.PositiveIntegerField()
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="projects")
    timeline = models.CharField(max_length=32, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CHOOSING_ARCHITECT
    )
    progress_pct = models.PositiveSmallIntegerField(default=0)
    next_action = models.CharField(max_length=120, blank=True)
    architect = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="architect_projects",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def hire(self, architect_user):
        self.architect = architect_user
        self.status = self.Status.UNDERWAY
        self.next_action = "Fund escrow to begin"
        self.save(update_fields=["architect", "status", "next_action"])


class Match(TimeStampedModel):
    """A curated project ↔ architect match; doubles as the architect's lead."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACCEPTED = "accepted", "Accepted by architect"
        DECLINED = "declined", "Declined by architect"
        HIRED = "hired", "Hired"
        WITHDRAWN = "withdrawn", "Withdrawn"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="matches")
    architect = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leads"
    )
    score = models.PositiveSmallIntegerField()  # match %
    tag = models.CharField(max_length=20, blank=True)  # BEST MATCH / STRONG / HOURLY OPTION
    reasons = models.JSONField(default=list, blank=True)
    rate_label = models.CharField(max_length=20, blank=True)  # FIXED QUOTE / HOURLY RATE
    rate_display = models.CharField(max_length=32, blank=True)  # "$21,400" / "$135/hr"
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROPOSED)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-score"]
        unique_together = [("project", "architect")]
        verbose_name_plural = "matches"

    def __str__(self):
        return f"{self.project} ↔ {self.architect.email} ({self.score}%)"

    def respond(self, accept: bool):
        """Architect accepts/declines a lead; re-callable to support the design's Undo."""
        if self.status in (self.Status.HIRED, self.Status.WITHDRAWN):
            raise ValueError(f"Lead is {self.status}; cannot respond.")
        self.status = self.Status.ACCEPTED if accept else self.Status.DECLINED
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])
