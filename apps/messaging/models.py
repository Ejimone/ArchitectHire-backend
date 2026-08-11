"""Real-time messaging (design: Account → Messages; Engagement → scoping chat).

HTTP POST is the write path (validation, files, contact gating); WebSocket is
delivery only. Contact details (emails/phones) are redacted in message bodies
until the project is hired — the design's 'details stay on-platform' rule.
"""

import re

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.core.storages import private_storage
from apps.orders.models import Order
from apps.projects.models import Project

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
REDACTION = "[hidden until you hire]"


class Thread(TimeStampedModel):
    """A conversation, usually attached to a project (scoping/engagement) or order."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True, related_name="threads"
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, null=True, blank=True, related_name="threads"
    )
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Thread #{self.pk} · {self.project or self.order or 'direct'}"

    @property
    def contact_gated(self) -> bool:
        """True until the client hires (design: contact details unlock at hire)."""
        if self.project:
            return self.project.status == Project.Status.CHOOSING_ARCHITECT
        return False

    def other_participants(self, user):
        return [p.user for p in self.participants.exclude(user=user).select_related("user")]


class ThreadParticipant(TimeStampedModel):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thread_memberships"
    )
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("thread", "user")]

    def unread_count(self) -> int:
        queryset = self.thread.messages.exclude(sender=self.user)
        if self.last_read_at:
            queryset = queryset.filter(created_at__gt=self.last_read_at)
        return queryset.count()


class Message(TimeStampedModel):
    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        FILE = "file", "File"
        CALL = "call", "Video call"

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent"
    )
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.TEXT)
    body = models.TextField(blank=True)
    file = models.FileField(upload_to="messages/%Y/%m/", storage=private_storage, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    call_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender.email}: {self.body[:40]}"

    @staticmethod
    def redact_contact_details(text: str) -> str:
        text = EMAIL_RE.sub(REDACTION, text)
        return PHONE_RE.sub(REDACTION, text)
