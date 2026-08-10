from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PopularSearch
from .services import query_index


class SearchView(APIView):
    """GET /api/v1/content/search/?q= — grouped site search."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        results = query_index(q) if len(q) >= 2 else {}
        popular = [{"term": p.term, "href": p.href} for p in PopularSearch.objects.all()[:8]]
        return Response({"query": q, "results": results, "popular": popular})
