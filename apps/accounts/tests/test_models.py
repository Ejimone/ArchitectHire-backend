import pytest
from django.contrib.auth import get_user_model

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
