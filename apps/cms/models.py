"""CMS models — everything the owner edits from Django admin.

Scoped blocks attach to a page (or a parameterized page like ``city:oakland``)
via a validated ``scope`` slug; the composed page endpoint assembles them.
"""

from django.db import models
from solo.models import SingletonModel

from apps.core.models import OrderableModel, PublishableModel, TimeStampedModel
from apps.core.scopes import validate_scope

from .models_editorial import (  # noqa: F401  (re-exported for admin/serializers/migrations)
    Author,
    BlogCategory,
    BlogContentBlock,
    BlogPost,
    CaseStudy,
    CaseStudyCategory,
    CaseStudyImage,
    ContactMethod,
    ContactSubmission,
    ContactTopic,
    Department,
    InspirationItem,
    InspirationLike,
    JobPosting,
    NewsletterSubscriber,
    Perk,
    PolicyPage,
    PolicySection,
)


class SiteSettings(SingletonModel):
    """Global site toggles & content (design: promo banner, trust bar, hero media mode)."""

    class HeroMedia(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        CAROUSEL = "carousel", "Carousel"

    promo_banner_enabled = models.BooleanField(default=True)
    promo_banner_text = models.CharField(max_length=255, blank=True)
    promo_banner_cta_label = models.CharField(max_length=64, blank=True)
    promo_banner_cta_href = models.CharField(max_length=255, blank=True)

    trust_bar_enabled = models.BooleanField(default=True)

    hero_media_mode = models.CharField(
        max_length=10, choices=HeroMedia.choices, default=HeroMedia.CAROUSEL
    )
    hero_image = models.ImageField(upload_to="cms/hero/", blank=True)
    hero_video_url = models.URLField(blank=True)

    contact_email_clients = models.EmailField(default="help@architecthire.com")
    contact_email_support = models.EmailField(default="help@architecthire.com")
    contact_email_privacy = models.EmailField(default="privacy@architecthire.com")

    class Meta:
        verbose_name = "Site settings"

    def __str__(self):
        return "Site settings"


class SocialLink(OrderableModel, TimeStampedModel):
    platform = models.CharField(max_length=32)  # X, LinkedIn, Instagram, Facebook
    url = models.URLField()

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.platform


class MediaAsset(TimeStampedModel):
    """Named image slot. The design references ~150 slots (see design/image-slot.js);
    each becomes a row here so the owner can swap any image on the site."""

    slot_key = models.SlugField(max_length=120, unique=True)
    image = models.ImageField(upload_to="cms/slots/", blank=True)
    alt_text = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True, help_text="Where this image appears")

    def __str__(self):
        return self.slot_key


class NavGroup(OrderableModel, TimeStampedModel):
    """A column/section inside one of the header mega-dropdowns."""

    class Menu(models.TextChoices):
        SERVICES = "services", "Services"
        PROJECTS = "projects", "Projects"
        LOCATIONS = "locations", "Locations"

    menu = models.CharField(max_length=16, choices=Menu.choices, db_index=True)
    heading = models.CharField(max_length=80, blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return f"{self.menu} · {self.heading or 'group'}"


class NavItem(OrderableModel, TimeStampedModel):
    group = models.ForeignKey(NavGroup, on_delete=models.CASCADE, related_name="items")
    label = models.CharField(max_length=80)
    sublabel = models.CharField(max_length=160, blank=True)
    href = models.CharField(max_length=255)
    price_hint = models.CharField(max_length=32, blank=True, help_text="e.g. $145 or $65/hr")
    is_featured = models.BooleanField(default=False, help_text="Rendered as the featured card")
    image = models.ImageField(upload_to="cms/nav/", blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.label


class FooterColumn(OrderableModel, TimeStampedModel):
    heading = models.CharField(max_length=80)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.heading


class FooterLink(OrderableModel, TimeStampedModel):
    column = models.ForeignKey(FooterColumn, on_delete=models.CASCADE, related_name="links")
    label = models.CharField(max_length=80)
    href = models.CharField(max_length=255)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.label


class ScopedBlock(TimeStampedModel, PublishableModel, OrderableModel):
    """Base for content blocks attached to a page scope.

    `group` separates several lists of the same block type on one page — e.g. the
    For Experts page shows hero stats and earnings stats, or three distinct grids
    of value props. Blank means "the page's default list".
    """

    scope = models.CharField(max_length=80, db_index=True, validators=[validate_scope])
    group = models.SlugField(
        max_length=40, blank=True, help_text="Optional section key, e.g. 'earnings' or 'tools'"
    )

    class Meta(OrderableModel.Meta):
        abstract = True


class FAQ(ScopedBlock):
    question = models.CharField(max_length=255)
    answer = models.TextField()

    class Meta(ScopedBlock.Meta):
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.question


class Stat(ScopedBlock):
    value = models.CharField(max_length=32)  # "3,200+", "48 hrs", "$0"
    label = models.CharField(max_length=120)

    def __str__(self):
        return f"{self.value} {self.label}"


class Step(ScopedBlock):
    """How-it-works step. Number comes from sort_order + 1."""

    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="cms/steps/", blank=True)

    def __str__(self):
        return self.title


class Testimonial(ScopedBlock):
    class Audience(models.TextChoices):
        CLIENT = "client", "Client"
        ARCHITECT = "architect", "Architect"
        EXPERT = "expert", "Expert"

    quote = models.TextField()
    name = models.CharField(max_length=80)
    role = models.CharField(max_length=120, blank=True)  # "Homeowner · Berkeley, CA"
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.CLIENT)
    photo = models.ImageField(upload_to="cms/testimonials/", blank=True)

    def __str__(self):
        return f"{self.name}: {self.quote[:40]}"


class ValueProp(ScopedBlock):
    icon = models.CharField(max_length=40, blank=True, help_text="Icon key the frontend maps")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.title


class TrustLogo(ScopedBlock):
    name = models.CharField(max_length=80)
    image = models.ImageField(upload_to="cms/logos/", blank=True)

    def __str__(self):
        return self.name


class CredentialBadge(ScopedBlock):
    label = models.CharField(max_length=40)  # AIA, NCARB, LEED AP...

    def __str__(self):
        return self.label


class UseCase(ScopedBlock):
    icon = models.CharField(max_length=40, blank=True)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    cta_label = models.CharField(max_length=64, blank=True)
    href = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.title


class Persona(ScopedBlock):
    """About-page hero persona (THE CLIENT / THE ARCHITECT / ...)."""

    kicker = models.CharField(max_length=40)
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)
    points = models.TextField(blank=True, help_text="One point per line")
    image = models.ImageField(upload_to="cms/personas/", blank=True)
    cta_label = models.CharField(max_length=64, blank=True)
    cta_href = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.title

    @property
    def points_list(self):
        return [line.strip() for line in self.points.splitlines() if line.strip()]


class Principle(ScopedBlock):
    """About-page numbered principle. Number = sort_order + 1."""

    title = models.CharField(max_length=120)
    body = models.TextField(blank=True)

    def __str__(self):
        return self.title


class HeroCarouselSlide(ScopedBlock):
    image = models.ImageField(upload_to="cms/carousel/", blank=True)
    caption = models.CharField(max_length=160, blank=True)
    name = models.CharField(max_length=80, blank=True)

    def __str__(self):
        return self.caption or f"Slide {self.pk}"


class CaseCard(ScopedBlock):
    """Curated case-study teaser card (e.g. the three on the landing page).

    Distinct from the CaseStudy model: these are hand-written card variants the
    owner places on marketing pages, each linking to a full case study.
    """

    category_tag = models.CharField(max_length=48, blank=True)  # "Backyard ADU"
    location = models.CharField(max_length=80, blank=True)  # "Oakland, CA"
    title = models.CharField(max_length=160)
    excerpt = models.TextField(blank=True)
    image = models.ImageField(upload_to="cms/case-cards/", blank=True)
    href = models.CharField(max_length=255, blank=True)
    stat1_value = models.CharField(max_length=32, blank=True)
    stat1_label = models.CharField(max_length=64, blank=True)
    stat2_value = models.CharField(max_length=32, blank=True)
    stat2_label = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.title


class EstimateTeaserOption(ScopedBlock):
    """One row of the landing 'Instant estimate' teaser dropdown."""

    label = models.CharField(max_length=80)  # "Backyard ADU (permit set)"
    price_range = models.CharField(max_length=48)  # "$2,400 – $6,500"
    bar_pct = models.PositiveSmallIntegerField(default=0, help_text="Range bar fill, 0–100")
    includes = models.TextField(blank=True, help_text="One 'What you get' line per row")

    def __str__(self):
        return f"{self.label} ({self.price_range})"

    @property
    def includes_list(self):
        return [line.strip() for line in self.includes.splitlines() if line.strip()]


class FeatureMatrixRow(ScopedBlock):
    """One row of a plan comparison table: a capability, and how it lands on each tier.

    The design's pricing table (design/marketing/Expert Pricing.dc.html) is a
    tri-state grid — included / limited / not included — which no other block
    type can express: every existing block stores prose, and a free-text list
    would let a typo silently drop a cell to "—". The columns are positional and
    line up with ``payments.SubscriptionPlan`` rows in their own sort order, so
    the table stays three wide only because that plan group is.
    """

    class Mark(models.TextChoices):
        YES = "yes", "Included"
        LIMITED = "limited", "Limited"
        NO = "no", "Not included"

    label = models.CharField(max_length=120)  # "Jurisdiction lookup"
    is_flagship = models.BooleanField(default=False, help_text="Shows the ★ FLAGSHIP chip")
    tier1 = models.CharField(max_length=8, choices=Mark.choices, default=Mark.NO)
    tier2 = models.CharField(max_length=8, choices=Mark.choices, default=Mark.NO)
    tier3 = models.CharField(max_length=8, choices=Mark.choices, default=Mark.NO)

    class Meta(ScopedBlock.Meta):
        verbose_name = "feature matrix row"
        verbose_name_plural = "feature matrix rows"

    def __str__(self):
        return self.label

    @property
    def marks(self):
        """The row's cells, left to right — one per plan in the table."""
        return [self.tier1, self.tier2, self.tier3]


class CopyBlock(TimeStampedModel):
    """A single piece of page copy — headline, subcopy, button label, badge text.

    Keyed per page scope (e.g. scope="landing", key="hero_cta") so literally every
    string the frontend renders is owner-editable. Buttons carry an optional href.
    """

    scope = models.CharField(max_length=80, db_index=True, validators=[validate_scope])
    key = models.SlugField(max_length=80)
    text = models.TextField(blank=True)
    href = models.CharField(max_length=255, blank=True, help_text="Only for links/buttons")

    class Meta:
        unique_together = [("scope", "key")]
        ordering = ["scope", "key"]

    def __str__(self):
        return f"{self.scope}:{self.key}"


class PageSEO(TimeStampedModel):
    page_key = models.CharField(max_length=80, unique=True, validators=[validate_scope])
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=320, blank=True)
    og_image = models.ImageField(upload_to="cms/og/", blank=True)
    canonical = models.URLField(blank=True)

    class Meta:
        verbose_name = "Page SEO"
        verbose_name_plural = "Page SEO"

    def __str__(self):
        return self.page_key
