from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.core.models import TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.STAFF)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Email-first user. Marketplace users authenticate through Clerk (clerk_id);
    Django admin (owner/staff) authenticates with a password as usual."""

    class Role(models.TextChoices):
        CLIENT = "client", "Client"
        ARCHITECT = "architect", "Architect"
        EXPERT = "expert", "Expert"
        STAFF = "staff", "Staff"

    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.CLIENT)
    clerk_id = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    phone = models.CharField(max_length=32, blank=True)
    avatar_url = models.URLField(blank=True)
    project_address = models.CharField(max_length=255, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    # Clerk session tokens omit email unless the JWT template adds it, so a
    # just-provisioned user carries a synthetic address. It must never reach a
    # screen — see `display_name` and `has_placeholder_email`.
    PLACEHOLDER_EMAIL_DOMAIN = "@pending.clerk.local"

    objects = UserManager()

    def __str__(self):
        return self.display_name

    @property
    def has_placeholder_email(self) -> bool:
        return self.email.endswith(self.PLACEHOLDER_EMAIL_DOMAIN)

    @property
    def display_name(self) -> str:
        """What the UI shows for this person, best available and never an id.

        Falls back through: full name → first name → the email's local part →
        a generic label. The placeholder address is skipped entirely, because
        "user_3Hkd8PK…@pending.clerk.local" is worse than showing nothing.
        """
        full = f"{self.first_name} {self.last_name}".strip()
        if full:
            return full
        if not self.has_placeholder_email:
            local = self.email.split("@")[0]
            if local:
                return local
        return "Your account"


class NotificationPreference(TimeStampedModel):
    """Per-user notification toggles (design: Account → Settings → Notifications)."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    milestone_updates = models.BooleanField(default=True)
    new_messages = models.BooleanField(default=True)
    requote_flags = models.BooleanField(default=True)
    tips_marketing = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification preferences for {self.user}"
