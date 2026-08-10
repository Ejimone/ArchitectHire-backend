from apps.cms.views import CachedContentView

from .models import City, State
from .serializers import (
    CityDetailSerializer,
    CitySerializer,
    StateDetailSerializer,
    StateListSerializer,
)


class StatesView(CachedContentView):
    """GET /api/v1/jurisdictions/states/ — all 52, with derived band/multiplier/timeline."""

    cache_slug = "_states"

    def build_payload(self, request):
        return {"states": StateListSerializer(State.objects.all(), many=True).data}


class StateDetailView(CachedContentView):
    def get_cache_slug(self, code=None):
        return f"_state:{code.upper()}"

    def build_payload(self, request, code=None):
        state = State.objects.filter(code=code.upper()).first()
        if state is None:
            return None
        return StateDetailSerializer(state).data


class CitiesView(CachedContentView):
    cache_slug = "_cities"

    def build_payload(self, request):
        queryset = City.objects.select_related("state")
        return {"cities": CitySerializer(queryset, many=True).data}


class CityDetailView(CachedContentView):
    def get_cache_slug(self, slug=None):
        return f"_city:{slug}"

    def build_payload(self, request, slug=None):
        city = City.objects.select_related("state").filter(slug=slug).first()
        if city is None:
            return None
        return CityDetailSerializer(city).data
