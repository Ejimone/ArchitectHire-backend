"""Sellable things and display pricing — all owner-editable.

Prices here power both the marketing pages (display) and the order/estimate
engines (calculation). Seeded from the design's exact figures.
"""

from django.db import models
from solo.models import SingletonModel

from apps.core.models import OrderableModel, TimeStampedModel


class ServiceCategory(OrderableModel, TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    icon = models.CharField(max_length=40, blank=True, help_text="Icon key the frontend maps")
    tagline = models.CharField(max_length=160, blank=True)
    has_detail = models.BooleanField(default=False)
    detail_href = models.CharField(max_length=255, blank=True)
    from_price = models.CharField(max_length=32, blank=True, help_text='e.g. "from $145"')

    class Meta(OrderableModel.Meta):
        verbose_name_plural = "service categories"

    def __str__(self):
        return self.name


class Service(OrderableModel, TimeStampedModel):
    class Tier(models.TextChoices):
        VOLUME = "volume", "Volume ($50–500)"
        CORE = "core", "Core ($500–5k)"
        FULL_PROJECT = "full_project", "Full-project ($5k+)"

    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    price_display = models.CharField(max_length=32)  # "from $145", "$65 – $90"
    price_unit = models.CharField(max_length=40, blank=True)  # "per session", "per sq ft"
    detail_href = models.CharField(max_length=255, blank=True)
    tier = models.CharField(max_length=16, choices=Tier.choices, blank=True)
    requires_stamp = models.BooleanField(default=False)
    is_popular = models.BooleanField(default=False)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.name


class Addon(OrderableModel, TimeStampedModel):
    """Estimate add-ons (design: structural $2,400 / MEP $3,200 / viz $1,800 / energy $1,200)."""

    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    sub = models.CharField(max_length=160, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return f"{self.label} (${self.price})"


class Plan(OrderableModel, TimeStampedModel):
    """Contract-type cards (Dynamic fixed quote / Hourly)."""

    key = models.SlugField(max_length=20, unique=True)
    tag = models.CharField(max_length=20)  # FLAGSHIP / FLEXIBLE
    title = models.CharField(max_length=80)
    blurb = models.TextField(blank=True)
    points = models.JSONField(default=list, blank=True)
    cta_label = models.CharField(max_length=64, blank=True)
    is_recommended = models.BooleanField(default=False)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.title


class ProjectType(OrderableModel, TimeStampedModel):
    class Group(models.TextChoices):
        RESIDENTIAL = "residential", "Residential"
        COMMERCIAL = "commercial", "Commercial"

    group = models.CharField(max_length=16, choices=Group.choices)
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    sub = models.CharField(max_length=160, blank=True)
    price_display = models.CharField(max_length=32, blank=True)  # "From $2,400"
    slot_id = models.CharField(max_length=40, blank=True)
    image_hint = models.CharField(max_length=120, blank=True)

    # SEO landing-page content (design: Project Landing.dc.html template fields)
    short_name = models.CharField(max_length=60, blank=True)
    kicker = models.CharField(max_length=80, blank=True)
    h1 = models.CharField(max_length=160, blank=True)
    intro = models.TextField(blank=True)
    body = models.TextField(blank=True)
    price_range = models.CharField(max_length=40, blank=True)  # "$2,400 – $6,800"
    bar_pct = models.PositiveSmallIntegerField(default=0)
    stats = models.JSONField(default=list, blank=True)  # [{"value": "...", "label": "..."}]
    includes = models.JSONField(default=list, blank=True)
    price_notes = models.JSONField(default=list, blank=True)
    steps = models.JSONField(default=list, blank=True)  # [{"title": "...", "description": "..."}]
    related = models.JSONField(default=list, blank=True)  # related project-type slugs

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.name


class RenderDeliverable(OrderableModel, TimeStampedModel):
    """Render order price matrix row (5 deliverables × 3 quality tiers)."""

    name = models.CharField(max_length=60, unique=True)
    unit = models.CharField(max_length=20)  # still / plan / view / tour
    conceptual = models.DecimalField(max_digits=8, decimal_places=2)
    professional = models.DecimalField(max_digits=8, decimal_places=2)
    photoreal = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.name

    def price_for(self, tier: str):
        return {
            "Conceptual": self.conceptual,
            "Professional": self.professional,
            "Photoreal": self.photoreal,
        }[tier]


class DraftingConfig(SingletonModel):
    """Drafting order pricing constants.

    Design: $78/hr, $30/sheet, $2,500 min as-built, $1,500 stamp, +25% rush.
    """

    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, default=78)
    asbuilt_per_sf = models.DecimalField(max_digits=5, decimal_places=2, default=0.25)
    asbuilt_minimum = models.DecimalField(max_digits=8, decimal_places=2, default=2500)
    per_sheet = models.DecimalField(max_digits=6, decimal_places=2, default=30)
    stamp_fee = models.DecimalField(max_digits=8, decimal_places=2, default=1500)
    rush_pct = models.PositiveSmallIntegerField(default=25)

    class Meta:
        verbose_name = "Drafting pricing config"

    def __str__(self):
        return "Drafting pricing config"


class EstimateConfig(SingletonModel):
    """Fixed-quote engine constants.

    Design: rate = 3.2 + 5.3·e^(−sqft/2600), ×(1.05 + score/100·0.35), ±8%.
    """

    rate_base = models.FloatField(default=3.2)
    rate_coeff = models.FloatField(default=5.3)
    rate_decay_sqft = models.FloatField(default=2600)
    round_to = models.PositiveSmallIntegerField(default=50)
    multiplier_floor = models.FloatField(default=1.05)
    multiplier_span = models.FloatField(default=0.35)
    range_pct = models.PositiveSmallIntegerField(default=8)

    class Meta:
        verbose_name = "Estimate engine config"

    def __str__(self):
        return "Estimate engine config"
