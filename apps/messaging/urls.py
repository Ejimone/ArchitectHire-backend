from django.urls import path

from .views import (
    MessageListCreateView,
    ScheduleCallView,
    ThreadListCreateView,
    ThreadReadView,
)

app_name = "messaging"

urlpatterns = [
    path("threads/", ThreadListCreateView.as_view(), name="threads"),
    path("threads/<int:pk>/messages/", MessageListCreateView.as_view(), name="messages"),
    path("threads/<int:pk>/read/", ThreadReadView.as_view(), name="read"),
    path("threads/<int:pk>/call/", ScheduleCallView.as_view(), name="call"),
]
