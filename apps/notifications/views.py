from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, PushSubscription


class NotificationListView(APIView):
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)[:50]
        unread = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        return Response(
            {
                "unread": unread,
                "notifications": [
                    {
                        "id": n.pk,
                        "kind": n.kind,
                        "title": n.title,
                        "body": n.body,
                        "data": n.data,
                        "read_at": n.read_at,
                        "created_at": n.created_at,
                    }
                    for n in notifications
                ],
            }
        )


class MarkReadView(APIView):
    def post(self, request):
        ids = request.data.get("ids")
        queryset = Notification.objects.filter(user=request.user, read_at__isnull=True)
        if ids:
            queryset = queryset.filter(pk__in=ids)
        updated = queryset.update(read_at=timezone.now())
        return Response({"marked": updated})


class PushSubscriptionView(APIView):
    """POST: register this browser for Web Push. DELETE {endpoint}: unregister."""

    def post(self, request):
        endpoint = request.data.get("endpoint")
        keys = request.data.get("keys") or {}
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return Response(
                {"detail": "endpoint, keys.p256dh and keys.auth required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
                "user_agent": request.headers.get("User-Agent", "")[:255],
            },
        )
        return Response({"status": "subscribed"}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        endpoint = request.data.get("endpoint")
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response({"status": "unsubscribed"})
