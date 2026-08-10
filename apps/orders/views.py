from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order
from .serializers import OrderCreateSerializer, OrderQuoteSerializer, OrderSerializer


class OrderQuoteView(APIView):
    """POST /api/v1/orders/quote/ — instant price, nothing persisted. Anonymous OK."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OrderQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data["quote"].as_dict())


class OrderCreateView(generics.CreateAPIView):
    """POST /api/v1/orders/ — place the order (anonymous checkout per the design)."""

    serializer_class = OrderCreateSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetailView(generics.RetrieveAPIView):
    """GET /api/v1/orders/{uuid}/ — order status (UUID acts as the access token
    for anonymous orders; signed-in owners see theirs via /orders/mine/)."""

    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [AllowAny]


class MyOrdersView(generics.ListAPIView):
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)
