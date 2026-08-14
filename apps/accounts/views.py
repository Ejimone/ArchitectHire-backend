from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.providers.models import OnboardingStatus

from .models import NotificationPreference, User
from .serializers import (
    NotificationPreferenceSerializer,
    RoleChangeSerializer,
    UserSerializer,
)

PROVIDER_ROLES = frozenset({User.Role.ARCHITECT, User.Role.EXPERT})


def _has_provider_identity(user) -> bool:
    """Whether the account already *is* a provider on the marketplace side.

    A bare profile row is not evidence of one: `providers.views._profile_for`
    creates it the moment anybody opens a /pro screen, browsing clients included.
    Only a wizard that has left `in_progress` marks an identity that the role must
    not be moved out from under.
    """
    profiles = (getattr(user, "architectprofile", None), getattr(user, "expertprofile", None))
    return any(
        p is not None and p.onboarding_status != OnboardingStatus.IN_PROGRESS for p in profiles
    )


class MeView(generics.RetrieveUpdateAPIView):
    """Current user's profile (`GET`/`PATCH /api/v1/auth/me/`)."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class MeRoleView(APIView):
    """Opt in to a provider role (`POST /api/v1/auth/me/role/`).

    One-way and one-time: only a client with no provider identity yet, and only
    towards architect or expert. Everything else is a refusal, not a validation
    error — the requests this endpoint exists to stop are deliberate ones.
    Responds with the same shape as `MeView` so callers can swap the user in place.
    """

    def post(self, request):
        serializer = RoleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data["role"]
        user = request.user
        if (
            role not in PROVIDER_ROLES
            or user.role != User.Role.CLIENT
            or _has_provider_identity(user)
        ):
            return Response(
                {"detail": "Only a client account without a provider profile can become one."},
                status=status.HTTP_403_FORBIDDEN,
            )
        user.role = role
        user.save(update_fields=["role"])
        return Response(UserSerializer(user).data)


class MePreferencesView(generics.RetrieveUpdateAPIView):
    """Current user's notification toggles (`GET`/`PATCH /api/v1/auth/me/preferences/`)."""

    serializer_class = NotificationPreferenceSerializer

    def get_object(self):
        prefs, _ = NotificationPreference.objects.get_or_create(user=self.request.user)
        return prefs
