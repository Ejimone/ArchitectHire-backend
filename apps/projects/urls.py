from django.urls import path

from .views import (
    EstimateCreateView,
    EstimateDetailView,
    HireView,
    LeadRespondView,
    MyLeadsView,
    ProjectDetailView,
    ProjectListCreateView,
    ProjectMatchesView,
)

app_name = "projects"

urlpatterns = [
    path("estimates/", EstimateCreateView.as_view(), name="estimate-create"),
    path("estimates/<uuid:pk>/", EstimateDetailView.as_view(), name="estimate-detail"),
    path("projects/", ProjectListCreateView.as_view(), name="project-list"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/matches/", ProjectMatchesView.as_view(), name="project-matches"),
    path("projects/<int:pk>/hire/", HireView.as_view(), name="project-hire"),
    path("providers/me/leads/", MyLeadsView.as_view(), name="my-leads"),
    path("leads/<int:pk>/<str:action>/", LeadRespondView.as_view(), name="lead-respond"),
]
