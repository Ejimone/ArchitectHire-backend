from django.urls import path

from .views import MyOrdersView, OrderCreateView, OrderDetailView, OrderQuoteView

app_name = "orders"

urlpatterns = [
    path("orders/quote/", OrderQuoteView.as_view(), name="quote"),
    path("orders/", OrderCreateView.as_view(), name="create"),
    path("orders/mine/", MyOrdersView.as_view(), name="mine"),
    path("orders/<uuid:pk>/", OrderDetailView.as_view(), name="detail"),
]
