from rest_framework import serializers

from .models import NotificationPreference, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "phone",
            "avatar_url",
            "project_address",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "date_joined"]

    def validate_role(self, value):
        if value == User.Role.STAFF and not self.instance.is_staff:
            raise serializers.ValidationError("Staff role cannot be self-assigned.")
        return value


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["milestone_updates", "new_messages", "requote_flags", "tips_marketing"]
