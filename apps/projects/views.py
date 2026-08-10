from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import Estimate
from .serializers import EstimateCreateSerializer, EstimateSerializer


class EstimateCreateView(generics.CreateAPIView):
    """POST /api/v1/estimates/ — instant estimate; anonymous allowed (pre-signup funnel)."""

    serializer_class = EstimateCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "estimates"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        estimate = serializer.save()
        return Response(EstimateSerializer(estimate).data, status=201)


class EstimateDetailView(generics.RetrieveAPIView):
    """GET /api/v1/estimates/{uuid}/ — shareable estimate snapshot."""

    queryset = Estimate.objects.select_related("state")
    serializer_class = EstimateSerializer
    permission_classes = [AllowAny]
