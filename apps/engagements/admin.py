from django.contrib import admin
from unfold.contrib.filters.admin import ChoicesDropdownFilter

from apps.studio.admin_base import (
    StudioModelAdmin,
    StudioTabularInline,
)
from apps.studio.display import WORKFLOW_LABELS, status_display

from .models import (
    ChangeRequest,
    Deliverable,
    Engagement,
    Milestone,
    RequoteFlag,
    TimeEntry,
)


class MilestoneInline(StudioTabularInline):
    model = Milestone
    extra = 0
    fields = ["title", "amount", "due_date", "status", "sort_order"]


@admin.register(Engagement)
class EngagementAdmin(StudioModelAdmin):
    list_display = ["project", "client", "provider", "kind", "total", "fee_percent", "status_pill"]
    list_filter = [("kind", ChoicesDropdownFilter), ("status", ChoicesDropdownFilter)]

    status_pill = status_display("status", WORKFLOW_LABELS)
    search_fields = ["project__title", "client__email", "provider__email"]
    inlines = [MilestoneInline]
    readonly_fields = ["fee_percent"]


@admin.register(Milestone)
class MilestoneAdmin(StudioModelAdmin):
    list_display = ["title", "engagement", "amount", "status_pill", "approved_at"]
    list_filter = [("status", ChoicesDropdownFilter)]
    search_fields = ["title", "engagement__project__title"]

    status_pill = status_display("status", WORKFLOW_LABELS)


@admin.register(RequoteFlag)
class RequoteFlagAdmin(StudioModelAdmin):
    list_display = ["engagement", "old_total", "new_total", "status_pill", "created_at"]
    list_filter = [("status", ChoicesDropdownFilter)]
    date_hierarchy = "created_at"

    status_pill = status_display("status", WORKFLOW_LABELS)


@admin.register(TimeEntry)
class TimeEntryAdmin(StudioModelAdmin):
    list_display = ["engagement", "provider", "date", "hours", "description"]
    date_hierarchy = "date"


@admin.register(Deliverable)
class DeliverableAdmin(StudioModelAdmin):
    list_display = ["name", "engagement", "uploaded_by", "stamped", "created_at"]
    list_filter = ["stamped"]


@admin.register(ChangeRequest)
class ChangeRequestAdmin(StudioModelAdmin):
    list_display = ["milestone", "requested_by", "created_at"]
    search_fields = ["note", "requested_by__email"]
    date_hierarchy = "created_at"
