from django.contrib import admin

from .models import PopularSearch, SearchIndexEntry


@admin.register(SearchIndexEntry)
class SearchIndexEntryAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "subtitle", "href"]
    list_filter = ["category"]
    search_fields = ["title", "subtitle", "keywords"]


@admin.register(PopularSearch)
class PopularSearchAdmin(admin.ModelAdmin):
    list_display = ["term", "href", "sort_order"]
    list_editable = ["sort_order"]
