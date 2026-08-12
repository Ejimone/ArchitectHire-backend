from django.contrib import admin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter

from apps.studio.admin_base import StudioModelAdmin, StudioTabularInline
from apps.studio.display import WORKFLOW_LABELS, status_display

from .models import Estimate, Match, Project


@admin.register(Estimate)
class EstimateAdmin(StudioModelAdmin):
    list_display = ["scope", "project_type", "sqft", "state", "low", "high", "user", "created_at"]
    list_filter = ["project_type", "state"]
    search_fields = ["scope", "project_type", "user__email"]
    readonly_fields = [field.name for field in Estimate._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


class MatchInline(StudioTabularInline):
    model = Match
    extra = 0
    fields = ["architect", "score", "tag", "rate_display", "status", "responded_at"]
    readonly_fields = ["responded_at"]
    show_change_link = True


@admin.register(Project)
class ProjectAdmin(StudioModelAdmin):
    """Read-mostly: projects are created by the matching flow, not by hand. Staff
    open them to inspect state or reassign an architect when a match goes wrong."""

    list_display = [
        "title",
        "owner",
        "status_pill",
        "progress_pct",
        "state",
        "architect",
        "created_at",
    ]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        "project_type",
        ("state", RelatedDropdownFilter),
    ]

    status_pill = status_display("status", WORKFLOW_LABELS)
    search_fields = ["title", "owner__email", "architect__email"]
    autocomplete_fields = ["owner", "architect", "state", "project_type_ref", "estimate"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [MatchInline]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(Match)
class MatchAdmin(StudioModelAdmin):
    list_display = ["project", "architect", "score", "tag", "status_pill", "responded_at"]
    list_filter = [("status", ChoicesDropdownFilter), "tag"]

    status_pill = status_display("status", WORKFLOW_LABELS)
    search_fields = ["project__title", "architect__email"]
    autocomplete_fields = ["project", "architect"]
    readonly_fields = ["responded_at"]

    def has_add_permission(self, request):
        return False
