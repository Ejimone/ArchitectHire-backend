from django.contrib import admin

from .models import Estimate


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display = ["scope", "project_type", "sqft", "state", "low", "high", "user", "created_at"]
    list_filter = ["project_type", "state"]
    readonly_fields = [field.name for field in Estimate._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
