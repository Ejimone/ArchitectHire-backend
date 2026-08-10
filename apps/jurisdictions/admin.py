from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from .models import City, State


@admin.register(State)
class StateAdmin(ImportExportModelAdmin):
    list_display = ["name", "code", "complexity_score", "band", "region", "largest_city"]
    list_editable = ["complexity_score"]
    list_filter = ["region"]
    search_fields = ["name", "code"]
    ordering = ["name"]


@admin.register(City)
class CityAdmin(ImportExportModelAdmin):
    list_display = ["name", "state", "county", "architect_count"]
    list_filter = ["state"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
