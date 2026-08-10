from django.contrib import admin

from .models import (
    ArchitectProfile,
    Credential,
    Discipline,
    ExpertProfile,
    PortfolioItem,
    Review,
)


@admin.register(Discipline)
class DisciplineAdmin(admin.ModelAdmin):
    list_display = ["name", "typical_rate", "licensure_tag", "requires_license", "requires_onsite"]
    list_editable = ["typical_rate"]


class CredentialInline(admin.TabularInline):
    model = Credential
    fk_name = "user"
    extra = 0
    fields = ["kind", "issuing_state", "number", "label", "status", "verified_at"]
    readonly_fields = ["verified_at"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ArchitectProfile)
class ArchitectProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "firm_name",
        "based_in",
        "onboarding_status",
        "accepting_work",
        "rating",
        "review_count",
    ]
    list_filter = ["onboarding_status", "accepting_work", "engagement_mode"]
    search_fields = ["user__email", "firm_name"]
    filter_horizontal = ["licensed_states", "project_types"]
    actions = ["approve_selected"]

    @admin.action(description="Approve · go live")
    def approve_selected(self, request, queryset):
        from django.utils import timezone

        queryset.update(onboarding_status="approved", approved_at=timezone.now())


@admin.register(ExpertProfile)
class ExpertProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "studio_name",
        "based_in",
        "onboarding_status",
        "accepting_work",
        "rating",
    ]
    list_filter = ["onboarding_status", "accepting_work", "pricing_mode", "disciplines"]
    search_fields = ["user__email", "studio_name"]
    filter_horizontal = ["licensed_states", "disciplines"]
    actions = ["approve_selected"]

    @admin.action(description="Approve · go live")
    def approve_selected(self, request, queryset):
        from django.utils import timezone

        queryset.update(onboarding_status="approved", approved_at=timezone.now())


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    """The verification queue: filter status=Uploaded, verify or reject."""

    list_display = ["user", "kind", "issuing_state", "number", "status", "created_at"]
    list_filter = ["status", "kind", "issuing_state"]
    search_fields = ["user__email", "number", "label"]
    readonly_fields = ["verified_at", "verified_by"]
    actions = ["verify_selected", "reject_selected"]
    date_hierarchy = "created_at"

    @admin.action(description="Verify selected")
    def verify_selected(self, request, queryset):
        for credential in queryset.filter(status="uploaded"):
            credential.verify(request.user)

    @admin.action(description="Reject selected")
    def reject_selected(self, request, queryset):
        for credential in queryset.filter(status="uploaded"):
            credential.reject(request.user)


@admin.register(PortfolioItem)
class PortfolioItemAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "meta", "sort_order"]
    search_fields = ["title", "user__email"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["provider", "reviewer_name", "rating", "is_published", "created_at"]
    list_filter = ["rating", "is_published"]
    list_editable = ["is_published"]
    search_fields = ["provider__email", "reviewer_name", "text"]
