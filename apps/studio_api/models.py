"""Studio persistence: staff sessions, staged edits, and published revisions."""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

# How long a studio login lasts, and how much of that has to be used up before a
# request renews it. Renewing on every request would mean a write per request; renewing
# only at the very end would log the owner out mid-edit.
SESSION_LIFETIME = timezone.timedelta(hours=12)
SESSION_RENEW_AFTER = timezone.timedelta(hours=6)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class StudioSession(TimeStampedModel):
    """A logged-in studio operator.

    Only the hash of the token is stored, so a database dump does not hand anyone a
    working session. Kept separate from `django.contrib.sessions` because the studio
    authenticates over the API with a bearer token rather than an admin cookie, and
    separate from Clerk because studio access is not a marketplace identity.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="studio_sessions"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"studio session for {self.user_id}"

    @classmethod
    def issue(cls, user) -> tuple["StudioSession", str]:
        """Create a session and return it alongside the raw token, which is the only
        time the raw value exists — it is never recoverable from the row."""
        raw = secrets.token_urlsafe(32)
        session = cls.objects.create(
            user=user,
            token_hash=hash_token(raw),
            expires_at=timezone.now() + SESSION_LIFETIME,
        )
        return session, raw

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    def touch(self) -> None:
        """Slide the expiry once a session is more than half spent."""
        if self.expires_at - timezone.now() < SESSION_LIFETIME - SESSION_RENEW_AFTER:
            self.expires_at = timezone.now() + SESSION_LIFETIME
            self.save(update_fields=["expires_at", "updated_at"])

    def revoke(self) -> None:
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at", "updated_at"])


class ContentDraft(TimeStampedModel):
    """One staged edit to one content row, not yet applied to the live site.

    A side table rather than a `status` field on each model, because only the 14
    `ScopedBlock` subclasses inherit `PublishableModel` — `CopyBlock` (which is most of
    what an editor touches), `MediaAsset`, `PageSEO` and the nav/footer models have no
    draft state at all, and `CopyBlock.unique_together (scope, key)` means a parallel
    draft row could not coexist with its published twin anyway.

    Reordering is expressed as ordinary `UPDATE` drafts carrying `sort_order`, so there
    is no fourth operation to apply, revert or reason about.
    """

    class Op(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"

    # The page this edit shows up on, so the publish queue can be filtered the way the
    # owner thinks about the site. Blank for site-wide rows (nav, footer, settings).
    scope = models.CharField(max_length=80, blank=True, db_index=True)
    model_label = models.CharField(max_length=60, db_index=True)
    # Null for CREATE: the row does not exist yet. Until it is published the canvas
    # refers to it by the negative of this draft's own id.
    object_id = models.PositiveIntegerField(null=True, blank=True)
    op = models.CharField(max_length=8, choices=Op.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="content_drafts",
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            # At most one pending edit per existing row: staging a delete over a pending
            # update replaces it rather than queueing both.
            models.UniqueConstraint(
                fields=["model_label", "object_id"],
                condition=models.Q(object_id__isnull=False),
                name="studio_api_one_draft_per_row",
            )
        ]

    def __str__(self):
        return f"{self.op} {self.model_label}:{self.object_id or f'new#{self.pk}'}"

    @property
    def canvas_id(self) -> int:
        """The id the canvas uses for this row — negative while a create is pending."""
        return self.object_id if self.object_id is not None else -self.pk


class ContentRevision(TimeStampedModel):
    """A published change set, kept so it can be inspected and rolled back.

    `changes` holds a full before/after snapshot per row rather than a diff: reverting
    has to be able to recreate a deleted row, and a diff cannot.
    """

    scope = models.CharField(max_length=80, blank=True, db_index=True)
    summary = models.CharField(max_length=255, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="content_revisions",
    )
    # [{"model_label", "object_id", "op", "before": {...}|null, "after": {...}|null}]
    changes = models.JSONField(default=list, blank=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.scope or 'site'} — {self.summary}"
