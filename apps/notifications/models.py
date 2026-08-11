from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    """In-app notification row — always written; push/email are delivery channels."""

    class Kind(models.TextChoices):
        NEW_MESSAGE = "new_message", "New message"
        MILESTONE = "milestone", "Milestone update"
        REQUOTE = "requote", "Re-quote flag"
        LEAD = "lead", "New lead"
        PAYOUT = "payout", "Payout"
        SYSTEM = "system", "System"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=320, blank=True)
    data = models.JSONField(default=dict, blank=True)  # e.g. {"thread_id": 3}
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} → {self.user.email}: {self.title}"


class PushSubscription(TimeStampedModel):
    """Browser Web Push subscription — how updates reach users with the site closed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Push sub for {self.user.email}"
