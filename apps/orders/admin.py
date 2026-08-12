from django.contrib import admin
from unfold.contrib.filters.admin import ChoicesDropdownFilter

from apps.studio.admin_base import (
    StudioModelAdmin,
    StudioTabularInline,
)
from apps.studio.display import WORKFLOW_LABELS, status_display

from .models import Order, OrderFile


class OrderFileInline(StudioTabularInline):
    model = OrderFile
    extra = 0


@admin.register(Order)
class OrderAdmin(StudioModelAdmin):
    list_display = ["id", "kind", "customer_email", "total", "status_pill", "expert", "created_at"]
    list_filter = [("kind", ChoicesDropdownFilter), ("status", ChoicesDropdownFilter)]

    status_pill = status_display("status", WORKFLOW_LABELS)
    search_fields = ["customer_email", "customer_name"]
    readonly_fields = ["subtotal", "stamp_amount", "rush_amount", "total", "config"]
    inlines = [OrderFileInline]
    date_hierarchy = "created_at"
