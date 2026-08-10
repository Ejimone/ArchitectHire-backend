from django.contrib import admin

from .models import (
    ChangeRequest,
    Deliverable,
    Engagement,
    Milestone,
    RequoteFlag,
    TimeEntry,
)


class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0
    fields = ["title", "amount", "due_date", "status", "sort_order"]


@admin.register(Engagement)
class EngagementAdmin(admin.ModelAdmin):
    list_display = ["project", "client", "provider", "kind", "total", "fee_percent", "status"]
    list_filter = ["kind", "status"]
    search_fields = ["project__title", "client__email", "provider__email"]
    inlines = [MilestoneInline]
    readonly_fields = ["fee_percent"]


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ["title", "engagement", "amount", "status", "approved_at"]
    list_filter = ["status"]


@admin.register(RequoteFlag)
class RequoteFlagAdmin(admin.ModelAdmin):
    list_display = ["engagement", "old_total", "new_total", "status", "created_at"]
    list_filter = ["status"]


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ["engagement", "provider", "date", "hours", "description"]
    date_hierarchy = "date"


@admin.register(Deliverable)
class DeliverableAdmin(admin.ModelAdmin):
    list_display = ["name", "engagement", "uploaded_by", "stamped", "created_at"]
    list_filter = ["stamped"]


admin.site.register(ChangeRequest)
