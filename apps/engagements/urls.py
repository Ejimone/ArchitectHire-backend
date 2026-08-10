from django.urls import path

from .views import (
    DeliverableListCreateView,
    EngagementDetailView,
    EngagementListCreateView,
    MilestoneActionView,
    MilestoneListCreateView,
    RequoteListCreateView,
    RequoteResolveView,
    TimeEntryListCreateView,
)

app_name = "engagements"

urlpatterns = [
    path("engagements/", EngagementListCreateView.as_view(), name="list-create"),
    path("engagements/<int:pk>/", EngagementDetailView.as_view(), name="detail"),
    path("engagements/<int:pk>/milestones/", MilestoneListCreateView.as_view(), name="milestones"),
    path("engagements/<int:pk>/requotes/", RequoteListCreateView.as_view(), name="requotes"),
    path(
        "engagements/<int:pk>/time-entries/", TimeEntryListCreateView.as_view(), name="time-entries"
    ),
    path(
        "engagements/<int:pk>/deliverables/",
        DeliverableListCreateView.as_view(),
        name="deliverables",
    ),
    path(
        "milestones/<int:pk>/<str:action>/", MilestoneActionView.as_view(), name="milestone-action"
    ),
    path("requotes/<int:pk>/<str:action>/", RequoteResolveView.as_view(), name="requote-resolve"),
]
