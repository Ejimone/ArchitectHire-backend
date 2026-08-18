"""Django-admin visibility for the Studio's own tables.

These are operational, not editorial: a wedged draft, a revision that needs reverting
from outside the Studio, a session that must be cut off. Without these registrations
the only way to reach any of them was a shell.
"""

from django.contrib import admin
from django.db import transaction
from django.utils import timezone

from apps.studio.admin_base import StudioModelAdmin

from . import drafts as engine
from .models import ContentDraft, ContentRevision, StudioSession


@admin.register(ContentDraft)
class ContentDraftAdmin(StudioModelAdmin):
    list_display = ["id", "scope", "model_label", "object_id", "op", "created_by", "updated_at"]
    list_filter = ["op", "model_label"]
    search_fields = ["scope", "model_label", "payload"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "updated_at"


@admin.register(ContentRevision)
class ContentRevisionAdmin(StudioModelAdmin):
    list_display = ["id", "scope", "summary", "applied_by", "created_at", "reverted_at"]
    list_filter = ["scope"]
    search_fields = ["scope", "summary"]
    readonly_fields = ["scope", "summary", "applied_by", "changes", "created_at", "reverted_at"]
    date_hierarchy = "created_at"
    actions = ["revert_selected"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Revert selected revisions")
    def revert_selected(self, request, queryset):
        done = 0
        for revision in queryset.filter(reverted_at__isnull=True):
            with transaction.atomic():
                engine.revert(revision, user=request.user)
            done += 1
        self.message_user(request, f"Reverted {done} revision(s).")


@admin.register(StudioSession)
class StudioSessionAdmin(StudioModelAdmin):
    list_display = ["id", "user", "created_at", "expires_at", "revoked_at", "is_active"]
    list_filter = ["revoked_at"]
    search_fields = ["user__email"]
    readonly_fields = ["user", "token_hash", "expires_at", "revoked_at", "created_at"]
    actions = ["revoke_selected"]

    def has_add_permission(self, request):
        return False

    @admin.display(boolean=True)
    def is_active(self, obj):
        return obj.is_active

    @admin.action(description="Revoke selected sessions")
    def revoke_selected(self, request, queryset):
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        self.message_user(request, f"Revoked {count} session(s).")
