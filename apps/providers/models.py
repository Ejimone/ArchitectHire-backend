"""Provider marketplace side: profiles, disciplines, credentials, portfolio, reviews.

Onboarding mirrors the design's 7-step wizards (Architect Account / Expert Account):
profiles accumulate data step by step, then submit → credential review → live.
Stamped work requires verified licensure in the client's jurisdiction — the
matching engine (projects app) enforces it via `licensed_states`.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.images import ProcessedImageField
from apps.core.models import OrderableModel, TimeStampedModel
from apps.core.storages import private_storage
from apps.jurisdictions.models import State


class Discipline(OrderableModel, TimeStampedModel):
    """Expert discipline taxonomy (6 in the design, with licensure gating flags)."""

    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=160, blank=True)
    typical_rate = models.CharField(max_length=32, blank=True)  # "$65–90/hr"
    licensure_tag = models.CharField(max_length=20, blank=True)  # NO LICENSE / LICENSE REQ / ...
    requires_license = models.BooleanField(default=False)
    requires_onsite = models.BooleanField(default=False)
    icon = models.CharField(max_length=40, blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.name


class OnboardingStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    SUBMITTED = "submitted", "Submitted"
    IN_REVIEW = "in_review", "Credential review"
    APPROVED = "approved", "Approved · live"
    REJECTED = "rejected", "Rejected"


class ProviderProfileBase(TimeStampedModel):
    """Shared provider fields (design: rates, capacity, coverage, payout entity)."""

    class Turnaround(models.TextChoices):
        FAST = "fast", "Fast"
        STANDARD = "standard", "Standard"
        RELAXED = "relaxed", "Relaxed"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)s"
    )
    bio = models.TextField(blank=True)
    headshot = ProcessedImageField(upload_to="providers/headshots/", blank=True)
    based_in = models.CharField(max_length=80, blank=True)
    remote_ok = models.BooleanField(default=True)
    hourly_rate = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    typical_turnaround = models.CharField(max_length=40, blank=True)
    capacity = models.PositiveSmallIntegerField(default=4)
    accepting_work = models.BooleanField(default=True)
    business_entity = models.CharField(max_length=40, blank=True)
    w9_on_file = models.BooleanField(default=False)
    licensed_states = models.ManyToManyField(State, blank=True, related_name="%(class)s_providers")

    onboarding_step = models.PositiveSmallIntegerField(default=1)
    onboarding_status = models.CharField(
        max_length=16, choices=OnboardingStatus.choices, default=OnboardingStatus.IN_PROGRESS
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    # Denormalized reputation (recomputed from reviews)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.PositiveIntegerField(default=0)
    projects_delivered = models.PositiveIntegerField(default=0)
    on_time_rate = models.PositiveSmallIntegerField(default=0)  # %
    avg_response = models.CharField(max_length=16, blank=True)  # "~2h"

    class Meta:
        abstract = True

    def submit(self):
        self.onboarding_status = OnboardingStatus.SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["onboarding_status", "submitted_at"])

    @property
    def is_live(self):
        return self.onboarding_status == OnboardingStatus.APPROVED


class ArchitectProfile(ProviderProfileBase):
    class EngagementMode(models.TextChoices):
        FIXED = "fixed", "Fixed quote"
        HOURLY = "hourly", "Hourly"
        BOTH = "both", "Both"

    firm_name = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=80, blank=True)
    years_licensed = models.PositiveSmallIntegerField(null=True, blank=True)
    website = models.URLField(blank=True)
    role_label = models.CharField(max_length=80, blank=True)  # "Principal Architect"
    engagement_mode = models.CharField(
        max_length=10, choices=EngagementMode.choices, default=EngagementMode.BOTH
    )
    travel_radius_mi = models.PositiveSmallIntegerField(default=35)
    stamp_jurisdictions = models.JSONField(
        default=list, blank=True, help_text="City/county chips, e.g. Oakland, Alameda County"
    )
    project_types = models.ManyToManyField(
        "catalog.ProjectType", blank=True, related_name="architects"
    )
    specialties = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"Architect: {self.user.email}"


class ExpertProfile(ProviderProfileBase):
    class PricingMode(models.TextChoices):
        HOURLY = "hourly", "Hourly"
        PER_DELIVERABLE = "per_deliverable", "Per deliverable"
        BOTH = "both", "Both"

    studio_name = models.CharField(max_length=120, blank=True)
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    disciplines = models.ManyToManyField(Discipline, blank=True, related_name="experts")
    software = models.JSONField(default=list, blank=True)
    deliverables = models.JSONField(default=list, blank=True)
    pricing_mode = models.CharField(
        max_length=16, choices=PricingMode.choices, default=PricingMode.HOURLY
    )
    onsite_radius_mi = models.PositiveSmallIntegerField(default=40)

    def __str__(self):
        return f"Expert: {self.user.email}"

    @property
    def requires_license(self):
        return any(d.requires_license for d in self.disciplines.all())


class Credential(TimeStampedModel):
    """Uploaded credential document with a verification state machine."""

    class Kind(models.TextChoices):
        ARCHITECT_LICENSE = "architect_license", "Architect license"
        PE_LICENSE = "pe_license", "PE license"
        NCARB = "ncarb", "NCARB record"
        EO_INSURANCE = "eo_insurance", "E&O insurance"
        CERTIFICATION = "certification", "Certification"
        BUSINESS_REGISTRATION = "business_registration", "Business registration (EIN)"
        W9 = "w9", "W-9"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded · ready to verify"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credentials"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    issuing_state = models.ForeignKey(
        State, on_delete=models.SET_NULL, null=True, blank=True, related_name="credentials"
    )
    number = models.CharField(max_length=60, blank=True)  # "C-38214", "PE-84021"
    label = models.CharField(max_length=120, blank=True)  # "LEED AP BD+C", "Autodesk Certified"
    expiration_date = models.DateField(null=True, blank=True)
    coverage_amount = models.CharField(max_length=20, blank=True)  # E&O: $1M / $2M / $5M
    document = models.FileField(upload_to="credentials/%Y/%m/", storage=private_storage, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADED)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_credentials",
    )
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.user.email} · {self.status}"

    def verify(self, staff_user):
        self.status = self.Status.VERIFIED
        self.verified_at = timezone.now()
        self.verified_by = staff_user
        self.save(update_fields=["status", "verified_at", "verified_by"])

    def reject(self, staff_user, notes=""):
        self.status = self.Status.REJECTED
        self.verified_by = staff_user
        if notes:
            self.review_notes = notes
        self.save(update_fields=["status", "verified_by", "review_notes"])


class PortfolioItem(OrderableModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portfolio_items"
    )
    image = ProcessedImageField(upload_to="providers/portfolio/", blank=True)
    title = models.CharField(max_length=120)
    meta = models.CharField(max_length=120, blank=True)  # "Type · location · year"

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.title


class Review(TimeStampedModel):
    """Client review of a provider (design: Matches profile 'Client reviews')."""

    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_received"
    )
    reviewer_name = models.CharField(max_length=80)
    reviewer_role = models.CharField(max_length=120, blank=True)  # "Homeowner · Berkeley, CA"
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    text = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}/5 for {self.provider.email} by {self.reviewer_name}"
