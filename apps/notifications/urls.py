from django.urls import path

from .views import MarkReadView, NotificationListView, PushSubscriptionView

app_name = "notifications"

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="list"),
    path("notifications/mark-read/", MarkReadView.as_view(), name="mark-read"),
    path("push-subscriptions/", PushSubscriptionView.as_view(), name="push-subscriptions"),
]
