from django.contrib import admin

from apps.studio.admin_base import (
    StudioImportExportAdmin,
    StudioModelAdmin,
    StudioSingletonAdmin,
    StudioTabularInline,
)

from .models import (
    Addon,
    DraftingConfig,
    EstimateConfig,
    Plan,
    ProjectType,
    RenderDeliverable,
    Service,
    ServiceCategory,
)


class ServiceInline(StudioTabularInline):
    model = Service
    extra = 0
    fields = ["name", "price_display", "price_unit", "tier", "is_popular", "sort_order"]
    show_change_link = True


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(StudioModelAdmin):
    list_display = ["name", "tagline", "from_price", "has_detail", "sort_order"]
    list_editable = ["sort_order"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [ServiceInline]


@admin.register(Service)
class ServiceAdmin(StudioImportExportAdmin):
    list_display = [
        "name",
        "category",
        "price_display",
        "price_unit",
        "tier",
        "is_popular",
        "sort_order",
    ]
    list_editable = ["price_display", "is_popular", "sort_order"]
    list_filter = ["category", "tier", "requires_stamp"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Addon)
class AddonAdmin(StudioModelAdmin):
    list_display = ["label", "key", "price", "sort_order"]
    list_editable = ["price", "sort_order"]


@admin.register(Plan)
class PlanAdmin(StudioModelAdmin):
    list_display = ["title", "tag", "is_recommended", "sort_order"]
    list_editable = ["sort_order"]


@admin.register(ProjectType)
class ProjectTypeAdmin(StudioModelAdmin):
    list_display = ["name", "group", "price_display", "sort_order"]
    list_editable = ["price_display", "sort_order"]
    list_filter = ["group"]
    search_fields = ["name", "slug"]  # required by autocomplete_fields elsewhere
    prepopulated_fields = {"slug": ["name"]}


@admin.register(RenderDeliverable)
class RenderDeliverableAdmin(StudioModelAdmin):
    list_display = ["name", "unit", "conceptual", "professional", "photoreal", "sort_order"]
    list_editable = ["conceptual", "professional", "photoreal", "sort_order"]


admin.site.register(DraftingConfig, StudioSingletonAdmin)
admin.site.register(EstimateConfig, StudioSingletonAdmin)
