from django.contrib import admin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.contrib.inlines.admin import NonrelatedTabularInline

from apps.studio.admin_base import StudioModelAdmin
from apps.studio.display import (
    CREDENTIAL_LABELS,
    ONBOARDING_LABELS,
    status_display,
    thumbnail_display,
)

from .models import (
    ArchitectProfile,
    Credential,
    Discipline,
    ExpertProfile,
    PortfolioItem,
    Review,
)


@admin.register(Discipline)
class DisciplineAdmin(StudioModelAdmin):
    list_display = ["name", "typical_rate", "licensure_tag", "requires_license", "requires_onsite"]
    list_editable = ["typical_rate"]


class CredentialInline(NonrelatedTabularInline):
    """A provider's credentials, shown on their profile.

    `Credential.user` points at User, not at the profile, so this cannot be an
    ordinary inline — which is why the original version was defined but never
    attached to anything. A nonrelated inline bridges the hop, and reviewing
    credentials alongside the profile is the whole approval workflow.
    """

    model = Credential
    extra = 0
    fields = ["kind", "issuing_state", "number", "label", "status", "verified_at"]
    readonly_fields = ["verified_at"]
    can_delete = False

    def get_form_queryset(self, obj):
        return Credential.objects.filter(user=obj.user).select_related("issuing_state")

    def save_new_instance(self, parent, instance):
        instance.user = parent.user

    def has_add_permission(self, request, obj=None):
        # Credentials are uploaded by providers, never created by staff.
        return False


@admin.register(ArchitectProfile)
class ArchitectProfileAdmin(StudioModelAdmin):
    list_display = [
        "user",
        "firm_name",
        "based_in",
        "onboarding_pill",
        "accepting_work",
        "rating",
        "review_count",
    ]
    list_filter = [
        ("onboarding_status", ChoicesDropdownFilter),
        "accepting_work",
        ("engagement_mode", ChoicesDropdownFilter),
    ]
    search_fields = ["user__email", "firm_name"]
    filter_horizontal = ["licensed_states", "project_types"]
    inlines = [CredentialInline]
    actions = ["approve_selected"]

    headshot_preview = thumbnail_display("headshot", description="Photo")
    onboarding_pill = status_display("onboarding_status", ONBOARDING_LABELS, "Onboarding")

    @admin.action(description="Approve · go live")
    def approve_selected(self, request, queryset):
        from django.utils import timezone

        queryset.update(onboarding_status="approved", approved_at=timezone.now())


@admin.register(ExpertProfile)
class ExpertProfileAdmin(StudioModelAdmin):
    list_display = [
        "user",
        "studio_name",
        "based_in",
        "onboarding_pill",
        "accepting_work",
        "rating",
    ]
    list_filter = [
        ("onboarding_status", ChoicesDropdownFilter),
        "accepting_work",
        ("pricing_mode", ChoicesDropdownFilter),
        ("disciplines", RelatedDropdownFilter),
    ]
    search_fields = ["user__email", "studio_name"]
    filter_horizontal = ["licensed_states", "disciplines"]
    inlines = [CredentialInline]
    actions = ["approve_selected"]

    headshot_preview = thumbnail_display("headshot", description="Photo")
    onboarding_pill = status_display("onboarding_status", ONBOARDING_LABELS, "Onboarding")

    @admin.action(description="Approve · go live")
    def approve_selected(self, request, queryset):
        from django.utils import timezone

        queryset.update(onboarding_status="approved", approved_at=timezone.now())


@admin.register(Credential)
class CredentialAdmin(StudioModelAdmin):
    """The verification queue: filter status=Uploaded, verify or reject."""

    list_display = ["user", "kind", "issuing_state", "number", "status_pill", "created_at"]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        ("issuing_state", RelatedDropdownFilter),
    ]
    search_fields = ["user__email", "number", "label"]
    readonly_fields = ["verified_at", "verified_by"]
    actions = ["verify_selected", "reject_selected"]
    date_hierarchy = "created_at"

    status_pill = status_display("status", CREDENTIAL_LABELS)

    @admin.action(description="Verify selected")
    def verify_selected(self, request, queryset):
        for credential in queryset.filter(status="uploaded"):
            credential.verify(request.user)

    @admin.action(description="Reject selected")
    def reject_selected(self, request, queryset):
        for credential in queryset.filter(status="uploaded"):
            credential.reject(request.user)


@admin.register(PortfolioItem)
class PortfolioItemAdmin(StudioModelAdmin):
    list_display = ["preview", "title", "user", "meta", "sort_order"]
    search_fields = ["title", "user__email"]
    list_editable = ["sort_order"]

    preview = thumbnail_display()


@admin.register(Review)
class ReviewAdmin(StudioModelAdmin):
    list_display = ["provider", "reviewer_name", "rating", "is_published", "created_at"]
    list_filter = ["rating", "is_published"]
    date_hierarchy = "created_at"
    list_editable = ["is_published"]
    search_fields = ["provider__email", "reviewer_name", "text"]
