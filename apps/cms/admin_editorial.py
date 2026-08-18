from django.contrib import admin
from unfold.contrib.filters.admin import (
    AllValuesCheckboxFilter,
    ChoicesDropdownFilter,
    RelatedDropdownFilter,
)

from apps.studio.admin_base import (
    StudioModelAdmin,
    StudioStackedInline,
    StudioTabularInline,
)
from apps.studio.display import status_display, thumbnail_display, truncated_display

from .models_editorial import (
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


class BlogContentBlockInline(StudioStackedInline):
    model = BlogContentBlock
    extra = 0
    fields = ["kind", "text", "attribution", "cta_label", "cta_href", "image", "sort_order"]


@admin.register(BlogPost)
class BlogPostAdmin(StudioModelAdmin):
    list_display = [
        "hero",
        "title",
        "category",
        "author",
        "status_pill",
        "is_featured",
        "published_at",
    ]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("category", RelatedDropdownFilter),
        "is_featured",
    ]
    list_editable = ["is_featured"]
    search_fields = ["title", "excerpt", "dek"]
    prepopulated_fields = {"slug": ["title"]}
    autocomplete_fields = ["category", "author"]
    inlines = [BlogContentBlockInline]
    date_hierarchy = "published_at"
    actions = ["publish_selected"]

    hero = thumbnail_display("hero_image")
    status_pill = status_display()

    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "author")}),
        ("Summary", {"fields": ("dek", "excerpt", "hero_image", "read_time")}),
        ("Publishing", {"fields": ("status", "published_at", "is_featured")}),
    )

    @admin.action(description="Publish selected")
    def publish_selected(self, request, queryset):
        for obj in queryset:
            obj.publish()


@admin.register(BlogCategory)
class BlogCategoryAdmin(StudioModelAdmin):
    list_display = ["name", "slug", "sort_order"]
    list_editable = ["sort_order"]
    search_fields = ["name", "slug"]  # required by BlogPostAdmin.autocomplete_fields
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Author)
class AuthorAdmin(StudioModelAdmin):
    list_display = ["portrait", "name", "role"]
    search_fields = ["name", "role"]

    portrait = thumbnail_display("photo")


class CaseStudyImageInline(StudioTabularInline):
    model = CaseStudyImage
    extra = 0
    fields = ["image", "caption", "sort_order"]


@admin.register(CaseStudy)
class CaseStudyAdmin(StudioModelAdmin):
    list_display = ["hero", "title", "category", "location", "status_pill", "is_featured"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("category", RelatedDropdownFilter),
        "is_featured",
    ]
    list_editable = ["is_featured"]
    search_fields = ["title", "excerpt", "location"]
    prepopulated_fields = {"slug": ["title"]}
    autocomplete_fields = ["category"]
    inlines = [CaseStudyImageInline]

    hero = thumbnail_display("hero_image")
    status_pill = status_display()
    fieldsets = (
        (
            None,
            {"fields": ("category", "title", "slug", "dek", "location", "excerpt", "hero_image")},
        ),
        (
            "Narrative",
            {"fields": ("brief", "challenge1", "challenge2", "match_narrative", "match_points")},
        ),
        ("Quote & outcome", {"fields": ("quote", "quote_by", "outcome1", "outcome2")}),
        ("Stats", {"fields": ("glance", "card_stats")}),
        (
            "Architect card",
            {"fields": ("architect_name", "architect_role", "architect_bio", "architect_tags")},
        ),
        ("Publishing", {"fields": ("status", "published_at", "is_featured")}),
    )
    actions = ["publish_selected"]

    @admin.action(description="Publish selected")
    def publish_selected(self, request, queryset):
        for obj in queryset:
            obj.publish()


@admin.register(CaseStudyCategory)
class CaseStudyCategoryAdmin(StudioModelAdmin):
    list_display = ["name", "slug", "sort_order"]
    list_editable = ["sort_order"]
    search_fields = ["name", "slug"]  # required by CaseStudyAdmin.autocomplete_fields
    prepopulated_fields = {"slug": ["name"]}


@admin.register(JobPosting)
class JobPostingAdmin(StudioModelAdmin):
    list_display = [
        "title",
        "department",
        "location",
        "employment_type",
        "status_pill",
        "sort_order",
    ]
    list_filter = [("status", ChoicesDropdownFilter), ("department", RelatedDropdownFilter)]
    list_editable = ["sort_order"]
    search_fields = ["title", "location"]

    status_pill = status_display()


@admin.register(Department)
class DepartmentAdmin(StudioModelAdmin):
    list_display = ["name", "sort_order"]
    list_editable = ["sort_order"]
    search_fields = ["name"]


@admin.register(Perk)
class PerkAdmin(StudioModelAdmin):
    list_display = ["title", "description", "sort_order"]
    list_editable = ["sort_order"]
    search_fields = ["title"]


@admin.register(ContactMethod)
class ContactMethodAdmin(StudioModelAdmin):
    list_display = ["kind", "title", "href", "sort_order"]
    list_editable = ["sort_order"]


@admin.register(ContactTopic)
class ContactTopicAdmin(StudioModelAdmin):
    list_display = ["label", "sort_order"]
    list_editable = ["sort_order"]


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(StudioModelAdmin):
    list_display = ["name", "email", "topic", "preview", "created_at"]
    # `topic` is a free-text CharField here (it mirrors ContactTopic.label rather
    # than pointing at it), so it needs a value filter, not a related one.
    list_filter = [("topic", AllValuesCheckboxFilter)]
    search_fields = ["name", "email", "message"]
    readonly_fields = ["name", "email", "topic", "message", "created_at"]
    date_hierarchy = "created_at"

    preview = truncated_display("message", 70, description="Message")

    def has_add_permission(self, request):
        return False


class PolicySectionInline(StudioStackedInline):
    model = PolicySection
    extra = 0
    fields = ["anchor", "heading", "body", "sort_order"]


@admin.register(PolicyPage)
class PolicyPageAdmin(StudioModelAdmin):
    list_display = ["title", "slug", "effective_date"]
    inlines = [PolicySectionInline]


@admin.register(InspirationItem)
class InspirationItemAdmin(StudioModelAdmin):
    list_display = ["preview", "title", "tag", "style", "likes_count", "status_pill", "sort_order"]
    list_filter = ["tag", "style", ("status", ChoicesDropdownFilter)]
    list_editable = ["sort_order"]
    search_fields = ["title", "tag", "style"]
    readonly_fields = ["likes_count"]

    preview = thumbnail_display()
    status_pill = status_display()


@admin.register(InspirationLike)
class InspirationLikeAdmin(StudioModelAdmin):
    """Read-only: likes are public input, kept visible so a spike can be inspected."""

    list_display = ["item", "user", "session_key", "created_at"]
    list_filter = [("item", RelatedDropdownFilter)]
    readonly_fields = ["item", "user", "session_key", "created_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(StudioModelAdmin):
    list_display = ["email", "source", "created_at"]
    search_fields = ["email"]

    def has_add_permission(self, request):
        return False
