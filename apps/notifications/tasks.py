"""Notification fanout: in-app row (always) + Web Push (site closed) + email fallback.

Honors each user's NotificationPreference toggles.
"""

import json
import logging

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)

PREFERENCE_FIELD = {
    "new_message": "new_messages",
    "milestone": "milestone_updates",
    "requote": "requote_flags",
    "lead": "new_messages",
    "payout": "milestone_updates",
    "system": None,  # always delivered
}


@shared_task(name="apps.notifications.tasks.notify")
def notify(user_id: int, kind: str, title: str, body: str = "", data: dict | None = None):
    from django.contrib.auth import get_user_model

    from apps.accounts.models import NotificationPreference

    from .models import Notification

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        return "user-missing"

    notification = Notification.objects.create(
        user=user, kind=kind, title=title, body=body, data=data or {}
    )

    # Live in-app delivery over the user's WebSocket group. The in-app row is
    # written unconditionally, so this event delivers unconditionally too —
    # the preference toggles below keep gating only push and email. Payload
    # mirrors GET /api/v1/notifications/ so clients handle one shape.
    channel_layer = get_channel_layer()
    if channel_layer is not None:
        unread = Notification.objects.filter(user=user, read_at__isnull=True).count()
        async_to_sync(channel_layer.group_send)(
            f"user_{user.pk}",
            {
                "type": "relay",
                "event": {
                    "type": "notification.new",
                    "unread": unread,
                    "notification": {
                        "id": notification.pk,
                        "kind": kind,
                        "title": title,
                        "body": body,
                        "data": data or {},
                        "read_at": None,
                        "created_at": notification.created_at.isoformat(),
                    },
                },
            },
        )

    prefs, _ = NotificationPreference.objects.get_or_create(user=user)
    pref_field = PREFERENCE_FIELD.get(kind)
    if pref_field and not getattr(prefs, pref_field, True):
        return "muted"

    pushed = _send_web_push(user, title, body, data or {})
    if not pushed:
        _send_email(user, title, body)
    return f"delivered push={pushed}"


def _send_web_push(user, title, body, data) -> bool:
    from pywebpush import WebPushException, webpush

    from .models import PushSubscription

    if not (settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY):
        return False

    payload = json.dumps({"title": title, "body": body, "data": data})
    delivered = False
    for subscription in PushSubscription.objects.filter(user=user):
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
            )
            delivered = True
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                subscription.delete()  # stale subscription — prune
            else:
                logger.warning("Web push failed for %s: %s", user.email, exc)
    return delivered


def _send_email(user, title, body):
    from django.core.mail import send_mail

    try:
        send_mail(
            subject=f"ArchitectHire · {title}",
            message=body or title,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception as exc:  # never let email failures break the caller
        logger.warning("Email notify failed for %s: %s", user.email, exc)
