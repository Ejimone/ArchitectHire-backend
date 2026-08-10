from django.contrib import admin

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
    JobPosting,
    NewsletterSubscriber,
    Perk,
    PolicyPage,
    PolicySection,
)


class BlogContentBlockInline(admin.StackedInline):
    model = BlogContentBlock
    extra = 0
    fields = ["kind", "text", "attribution", "cta_label", "cta_href", "image", "sort_order"]


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "author", "status", "is_featured", "published_at"]
    list_filter = ["status", "category", "is_featured"]
    list_editable = ["is_featured"]
    search_fields = ["title", "excerpt"]
    prepopulated_fields = {"slug": ["title"]}
    inlines = [BlogContentBlockInline]
    date_hierarchy = "published_at"
    actions = ["publish_selected"]

    @admin.action(description="Publish selected")
    def publish_selected(self, request, queryset):
        for obj in queryset:
            obj.publish()


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "sort_order"]
    list_editable = ["sort_order"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ["name", "role"]
    search_fields = ["name"]


class CaseStudyImageInline(admin.TabularInline):
    model = CaseStudyImage
    extra = 0
    fields = ["image", "caption", "sort_order"]


@admin.register(CaseStudy)
class CaseStudyAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "location", "status", "is_featured"]
    list_filter = ["status", "category", "is_featured"]
    list_editable = ["is_featured"]
    search_fields = ["title", "excerpt", "location"]
    prepopulated_fields = {"slug": ["title"]}
    inlines = [CaseStudyImageInline]
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
class CaseStudyCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "sort_order"]
    list_editable = ["sort_order"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ["title", "department", "location", "employment_type", "status", "sort_order"]
    list_filter = ["status", "department"]
    list_editable = ["sort_order"]


admin.site.register(Department)
admin.site.register(Perk)


@admin.register(ContactMethod)
class ContactMethodAdmin(admin.ModelAdmin):
    list_display = ["kind", "title", "href", "sort_order"]
    list_editable = ["sort_order"]


admin.site.register(ContactTopic)


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "topic", "created_at"]
    list_filter = ["topic"]
    readonly_fields = ["name", "email", "topic", "message", "created_at"]

    def has_add_permission(self, request):
        return False


class PolicySectionInline(admin.StackedInline):
    model = PolicySection
    extra = 0
    fields = ["anchor", "heading", "body", "sort_order"]


@admin.register(PolicyPage)
class PolicyPageAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "effective_date"]
    inlines = [PolicySectionInline]


@admin.register(InspirationItem)
class InspirationItemAdmin(admin.ModelAdmin):
    list_display = ["title", "tag", "style", "likes_count", "status", "sort_order"]
    list_filter = ["tag", "style", "status"]
    list_editable = ["sort_order"]
    readonly_fields = ["likes_count"]


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ["email", "source", "created_at"]
    search_fields = ["email"]

    def has_add_permission(self, request):
        return False
