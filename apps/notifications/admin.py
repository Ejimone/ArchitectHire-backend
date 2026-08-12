from django.contrib import admin

from apps.studio.admin_base import StudioModelAdmin

from .models import Notification, PushSubscription


@admin.register(Notification)
class NotificationAdmin(StudioModelAdmin):
    list_display = ["user", "kind", "title", "read_at", "created_at"]
    list_filter = ["kind"]
    search_fields = ["user__email", "title"]


@admin.register(PushSubscription)
class PushSubscriptionAdmin(StudioModelAdmin):
    list_display = ["user", "endpoint", "created_at"]
    search_fields = ["user__email"]
