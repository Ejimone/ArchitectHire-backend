from django.contrib import admin

from apps.studio.admin_base import StudioModelAdmin

from .models import PopularSearch, SearchIndexEntry


@admin.register(SearchIndexEntry)
class SearchIndexEntryAdmin(StudioModelAdmin):
    list_display = ["title", "category", "subtitle", "href"]
    list_filter = ["category"]
    search_fields = ["title", "subtitle", "keywords"]


@admin.register(PopularSearch)
class PopularSearchAdmin(StudioModelAdmin):
    list_display = ["term", "href", "sort_order"]
    list_editable = ["sort_order"]
