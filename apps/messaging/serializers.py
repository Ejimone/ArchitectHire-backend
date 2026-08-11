from django.core.cache import cache
from rest_framework import serializers

from .consumers import presence_key
from .models import Message, Thread


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    file = serializers.FileField(read_only=True, use_url=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "kind",
            "body",
            "file",
            "file_name",
            "file_size",
            "call_time",
            "sender",
            "sender_name",
            "is_mine",
            "created_at",
        ]

    def get_sender_name(self, obj):
        return obj.sender.display_name

    def get_is_mine(self, obj):
        request = self.context.get("request")
        return bool(request and request.user == obj.sender)


class ThreadSerializer(serializers.ModelSerializer):
    other_name = serializers.SerializerMethodField()
    other_user_id = serializers.SerializerMethodField()
    other_online = serializers.SerializerMethodField()
    context_label = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = [
            "id",
            "project",
            "order",
            "archived",
            "contact_gated",
            "other_name",
            "other_user_id",
            "other_online",
            "context_label",
            "last_message",
            "unread_count",
            "updated_at",
        ]

    def _other(self, obj):
        request = self.context["request"]
        others = obj.other_participants(request.user)
        return others[0] if others else None

    def get_other_name(self, obj):
        other = self._other(obj)
        return other.display_name if other else ""

    def get_other_user_id(self, obj):
        """Counterpart's pk, so live presence events (keyed by user id) can be
        mapped back to threads client-side."""
        other = self._other(obj)
        return other.pk if other else None

    def get_other_online(self, obj):
        other = self._other(obj)
        return bool(other and cache.get(presence_key(other.pk)))

    def get_context_label(self, obj):
        if obj.project:
            return obj.project.title
        if obj.order:
            return obj.order.get_kind_display()
        return ""

    def get_last_message(self, obj):
        last = obj.messages.last()
        if last is None:
            return None
        return {"body": last.body[:120], "kind": last.kind, "created_at": last.created_at}

    def get_unread_count(self, obj):
        request = self.context["request"]
        participant = obj.participants.filter(user=request.user).first()
        return participant.unread_count() if participant else 0
