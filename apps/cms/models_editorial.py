"""Editorial content: blog/guides, case studies, careers, contact, policies, inspiration."""

from django.conf import settings
from django.db import models

from apps.core.models import OrderableModel, PublishableModel, TimeStampedModel


class Author(TimeStampedModel):
    name = models.CharField(max_length=80)  # may carry credentials: "Maya Ellison, AIA"
    role = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    photo = models.ImageField(upload_to="cms/authors/", blank=True)

    def __str__(self):
        return self.name


class BlogCategory(OrderableModel, TimeStampedModel):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=40, unique=True)

    class Meta(OrderableModel.Meta):
        verbose_name_plural = "blog categories"

    def __str__(self):
        return self.name


class BlogPost(TimeStampedModel, PublishableModel):
    category = models.ForeignKey(
        BlogCategory, on_delete=models.SET_NULL, null=True, related_name="posts"
    )
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=160)
    dek = models.CharField(max_length=320, blank=True, help_text="Subtitle under the headline")
    excerpt = models.TextField(blank=True)
    hero_image = models.ImageField(upload_to="cms/blog/", blank=True)
    author = models.ForeignKey(Author, on_delete=models.SET_NULL, null=True, related_name="posts")
    read_time = models.CharField(max_length=20, blank=True)  # "7 min read"
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title


class BlogContentBlock(OrderableModel):
    """Rich article body as editable rows (never raw JSON in admin)."""

    class Kind(models.TextChoices):
        PARAGRAPH = "paragraph", "Paragraph"
        HEADING = "h2", "Section heading"
        LIST = "list", "Bulleted list (one item per line)"
        PULLQUOTE = "pullquote", "Pull quote"
        CTA = "cta", "Inline CTA block"
        IMAGE = "image", "Image"

    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name="content_blocks")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.PARAGRAPH)
    text = models.TextField(blank=True)
    attribution = models.CharField(max_length=120, blank=True, help_text="Pull quote attribution")
    cta_label = models.CharField(max_length=64, blank=True)
    cta_href = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="cms/blog/blocks/", blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return f"{self.kind}: {self.text[:40]}"


class CaseStudyCategory(OrderableModel, TimeStampedModel):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=40, unique=True)

    class Meta(OrderableModel.Meta):
        verbose_name_plural = "case study categories"

    def __str__(self):
        return self.name


class CaseStudy(TimeStampedModel, PublishableModel):
    """Structured case-study narrative (design: Case Study.dc.html)."""

    category = models.ForeignKey(
        CaseStudyCategory, on_delete=models.SET_NULL, null=True, related_name="case_studies"
    )
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=160)
    dek = models.CharField(max_length=320, blank=True)
    location = models.CharField(max_length=80, blank=True)
    excerpt = models.TextField(blank=True)
    hero_image = models.ImageField(upload_to="cms/case-studies/", blank=True)

    brief = models.TextField(blank=True)
    challenge1 = models.TextField(blank=True)
    challenge2 = models.TextField(blank=True)
    match_narrative = models.TextField(blank=True)
    match_points = models.JSONField(default=list, blank=True)
    quote = models.TextField(blank=True)
    quote_by = models.CharField(max_length=120, blank=True)
    outcome1 = models.TextField(blank=True)
    outcome2 = models.TextField(blank=True)
    glance = models.JSONField(default=list, blank=True, help_text='[{"k": "Project", "v": "..."}]')
    card_stats = models.JSONField(
        default=list, blank=True, help_text='[{"value": "...", "key": "..."}]'
    )

    architect_name = models.CharField(max_length=80, blank=True)
    architect_role = models.CharField(max_length=120, blank=True)
    architect_bio = models.TextField(blank=True)
    architect_tags = models.JSONField(default=list, blank=True)

    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        verbose_name_plural = "case studies"

    def __str__(self):
        return self.title


class CaseStudyImage(OrderableModel):
    case_study = models.ForeignKey(CaseStudy, on_delete=models.CASCADE, related_name="gallery")
    image = models.ImageField(upload_to="cms/case-studies/gallery/")
    caption = models.CharField(max_length=160, blank=True)

    class Meta(OrderableModel.Meta):
        pass


class Department(OrderableModel, TimeStampedModel):
    name = models.CharField(max_length=60, unique=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.name


class JobPosting(TimeStampedModel, PublishableModel, OrderableModel):
    title = models.CharField(max_length=120)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="jobs"
    )
    location = models.CharField(max_length=80, blank=True)
    employment_type = models.CharField(max_length=40, blank=True)  # Full-time / Contract
    description = models.TextField(blank=True)
    apply_href = models.CharField(max_length=255, blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.title


class Perk(OrderableModel, TimeStampedModel):
    title = models.CharField(max_length=80)
    description = models.TextField(blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.title


class ContactMethod(OrderableModel, TimeStampedModel):
    kind = models.CharField(max_length=30)  # CLIENTS / ARCHITECTS / SUPPORT
    title = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    link_label = models.CharField(max_length=80, blank=True)
    href = models.CharField(max_length=255, blank=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return f"{self.kind}: {self.title}"


class ContactTopic(OrderableModel, TimeStampedModel):
    label = models.CharField(max_length=80, unique=True)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.label


class ContactSubmission(TimeStampedModel):
    name = models.CharField(max_length=80)
    email = models.EmailField()
    topic = models.CharField(max_length=80, blank=True)
    message = models.TextField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} · {self.topic}"


class PolicyPage(TimeStampedModel):
    slug = models.SlugField(max_length=40, unique=True)  # privacy / terms
    title = models.CharField(max_length=120)
    effective_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title


class PolicySection(OrderableModel, TimeStampedModel):
    page = models.ForeignKey(PolicyPage, on_delete=models.CASCADE, related_name="sections")
    anchor = models.SlugField(max_length=40)
    heading = models.CharField(max_length=160)
    body = models.TextField(help_text="Paragraphs separated by blank lines")

    class Meta(OrderableModel.Meta):
        unique_together = [("page", "anchor")]

    def __str__(self):
        return self.heading


class InspirationItem(TimeStampedModel, PublishableModel, OrderableModel):
    title = models.CharField(max_length=120)
    tag = models.CharField(max_length=40, blank=True)  # category chip
    style = models.CharField(max_length=40, blank=True)  # design style
    image = models.ImageField(upload_to="cms/inspiration/", blank=True)
    palette = models.JSONField(default=list, blank=True, help_text="4 hex colors")
    masonry_height = models.PositiveSmallIntegerField(default=280)
    likes_count = models.PositiveIntegerField(default=0)

    class Meta(OrderableModel.Meta):
        pass

    def __str__(self):
        return self.title


class InspirationLike(TimeStampedModel):
    item = models.ForeignKey(InspirationItem, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    session_key = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_like_per_user",
            ),
            models.UniqueConstraint(
                fields=["item", "session_key"],
                condition=models.Q(user__isnull=True) & ~models.Q(session_key=""),
                name="unique_like_per_session",
            ),
        ]


class NewsletterSubscriber(TimeStampedModel):
    email = models.EmailField(unique=True)
    source = models.CharField(max_length=40, blank=True, default="blog")

    def __str__(self):
        return self.email
