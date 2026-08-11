import pytest
from django.contrib.auth import get_user_model

from apps.accounts.factories import UserFactory
from apps.accounts.models import NotificationPreference

User = get_user_model()


@pytest.mark.django_db
class TestUser:
    def test_create_user_with_email(self):
        user = User.objects.create_user(email="jane@example.com", password="s3cret-pass")
        assert user.email == "jane@example.com"
        assert user.role == User.Role.CLIENT
        assert not user.is_staff
        assert user.check_password("s3cret-pass")

    def test_create_user_requires_email(self):
        with pytest.raises(ValueError):
            User.objects.create_user(email="", password="x")

    def test_create_superuser(self):
        admin = User.objects.create_superuser(email="owner@example.com", password="s3cret-pass")
        assert admin.is_staff and admin.is_superuser
        assert admin.role == User.Role.STAFF

    def test_notification_preferences_auto_created(self):
        user = User.objects.create_user(email="prefs@example.com", password="s3cret-pass")
        prefs = NotificationPreference.objects.get(user=user)
        assert prefs.milestone_updates is True
        assert prefs.new_messages is True
        assert prefs.requote_flags is True
        assert prefs.tips_marketing is False

    def test_create_superuser_requires_both_flags(self):
        with pytest.raises(ValueError, match="is_staff=True"):
            User.objects.create_superuser(
                email="notstaff@example.com", password="s3cret-pass", is_staff=False
            )
        with pytest.raises(ValueError, match="is_superuser=True"):
            User.objects.create_superuser(
                email="notsuper@example.com", password="s3cret-pass", is_superuser=False
            )

    def test_str_representations(self):
        user = User.objects.create_user(email="str@example.com", password="s3cret-pass")
        # __str__ is the display name — the email's local part when no name is set.
        assert str(user) == "str"
        assert str(user.notification_preferences) == "Notification preferences for str"


@pytest.mark.django_db
class TestDisplayName:
    """The UI must never show a Clerk id or the synthetic pending address."""

    def test_full_name_wins(self):
        user = UserFactory(first_name="Maya", last_name="Ellis", email="maya@example.com")
        assert user.display_name == "Maya Ellis"
        assert str(user) == "Maya Ellis"

    def test_first_name_alone(self):
        user = UserFactory(first_name="Maya", last_name="", email="maya@example.com")
        assert user.display_name == "Maya"

    def test_email_local_part_when_no_name(self):
        user = UserFactory(first_name="", last_name="", email="maya.ellis@example.com")
        assert user.display_name == "maya.ellis"

    def test_placeholder_email_is_never_shown(self):
        user = UserFactory(
            first_name="",
            last_name="",
            email="user_3Hkd8PKFFZtBnolebE64ExCjYS8@pending.clerk.local",
        )
        assert user.has_placeholder_email is True
        assert user.display_name == "Your account"
        assert "user_" not in user.display_name

    def test_serializer_exposes_display_fields(self):
        from apps.accounts.serializers import UserSerializer

        user = UserFactory(first_name="Maya", last_name="", email="maya@example.com")
        data = UserSerializer(user).data
        assert data["display_name"] == "Maya"
        assert data["has_placeholder_email"] is False
