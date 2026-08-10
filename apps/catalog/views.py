"""Catalog content endpoints — cached like CMS content (they power marketing pages)."""

from apps.cms.views import CachedContentView

from .models import (
    Addon,
    DraftingConfig,
    Plan,
    ProjectType,
    RenderDeliverable,
    ServiceCategory,
)
from .serializers import (
    AddonSerializer,
    DraftingConfigSerializer,
    PlanSerializer,
    ProjectTypeDetailSerializer,
    ProjectTypeSerializer,
    RenderDeliverableSerializer,
    ServiceCategorySerializer,
)


class CategoriesView(CachedContentView):
    """GET /api/v1/catalog/categories/ — 8 groups with their services (the full catalog)."""

    cache_slug = "_catalog"

    def build_payload(self, request):
        queryset = ServiceCategory.objects.prefetch_related("services")
        return {"categories": ServiceCategorySerializer(queryset, many=True).data}


class AddonsView(CachedContentView):
    cache_slug = "_addons"

    def build_payload(self, request):
        return {"addons": AddonSerializer(Addon.objects.all(), many=True).data}


class PlansView(CachedContentView):
    cache_slug = "_plans"

    def build_payload(self, request):
        return {"plans": PlanSerializer(Plan.objects.all(), many=True).data}


class ProjectTypesView(CachedContentView):
    cache_slug = "_project_types"

    def build_payload(self, request):
        return {"project_types": ProjectTypeSerializer(ProjectType.objects.all(), many=True).data}


class ProjectTypeDetailView(CachedContentView):
    """GET /api/v1/catalog/project-types/{slug}/ — full SEO landing payload."""

    def get_cache_slug(self, slug=None):
        return f"_project_type:{slug}"

    def build_payload(self, request, slug=None):
        project_type = ProjectType.objects.filter(slug=slug).first()
        if project_type is None:
            return None
        return ProjectTypeDetailSerializer(project_type).data


class RenderMatrixView(CachedContentView):
    cache_slug = "_render_matrix"

    def build_payload(self, request):
        return {
            "deliverables": RenderDeliverableSerializer(
                RenderDeliverable.objects.all(), many=True
            ).data,
            "quality_tiers": [
                {"key": "Conceptual", "sub": "Fast, clean, idea-level"},
                {"key": "Professional", "sub": "Real materials & lighting"},
                {"key": "Photoreal", "sub": "Gallery-grade marketing"},
            ],
        }


class DraftingPricingView(CachedContentView):
    cache_slug = "_drafting_pricing"

    def build_payload(self, request):
        return DraftingConfigSerializer(DraftingConfig.get_solo()).data
