from rest_framework import serializers

from .models import NotificationPreference, User


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    has_placeholder_email = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "display_name",
            "has_placeholder_email",
            "first_name",
            "last_name",
            "role",
            "phone",
            "avatar_url",
            "project_address",
            "date_joined",
        ]
        # `role` is read-only here on purpose: onboarding forwards whole form
        # payloads to PATCH /auth/me/, so a crafted `role` field would otherwise
        # promote a client account. Provider roles are opted into through
        # POST /auth/me/role/ instead.
        read_only_fields = ["id", "email", "role", "date_joined"]

    def validate_role(self, value):
        # Unreachable while `role` is read-only — kept so that a future writable
        # path cannot hand out staff by omission.
        if value == User.Role.STAFF and not self.instance.is_staff:
            raise serializers.ValidationError("Staff role cannot be self-assigned.")
        return value


class RoleChangeSerializer(serializers.Serializer):
    """The one deliberate way to leave the client role (`POST /auth/me/role/`).

    A plain `CharField`, not a `ChoiceField`: which roles an account may move to is
    the view's decision, and every refused role — `staff` above all — has to read
    as a refusal rather than as a malformed request.
    """

    role = serializers.CharField()


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["milestone_updates", "new_messages", "requote_flags", "tips_marketing"]
