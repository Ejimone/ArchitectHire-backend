from django.contrib import admin

from apps.studio.admin_base import StudioImportExportAdmin

from .models import City, State


@admin.register(State)
class StateAdmin(StudioImportExportAdmin):
    list_display = ["name", "code", "complexity_score", "band", "region", "largest_city"]
    list_editable = ["complexity_score"]
    list_filter = ["region"]
    search_fields = ["name", "code"]
    ordering = ["name"]


@admin.register(City)
class CityAdmin(StudioImportExportAdmin):
    list_display = ["name", "state", "county", "architect_count"]
    list_filter = ["state"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
