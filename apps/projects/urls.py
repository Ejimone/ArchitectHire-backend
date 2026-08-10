from django.urls import path

from .views import EstimateCreateView, EstimateDetailView

app_name = "projects"

urlpatterns = [
    path("estimates/", EstimateCreateView.as_view(), name="estimate-create"),
    path("estimates/<uuid:pk>/", EstimateDetailView.as_view(), name="estimate-detail"),
]
