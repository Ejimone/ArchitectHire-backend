from rest_framework import generics

from .models import NotificationPreference
from .serializers import NotificationPreferenceSerializer, UserSerializer


class MeView(generics.RetrieveUpdateAPIView):
    """Current user's profile (`GET`/`PATCH /api/v1/auth/me/`)."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class MePreferencesView(generics.RetrieveUpdateAPIView):
    """Current user's notification toggles (`GET`/`PATCH /api/v1/auth/me/preferences/`)."""

    serializer_class = NotificationPreferenceSerializer

    def get_object(self):
        prefs, _ = NotificationPreference.objects.get_or_create(user=self.request.user)
        return prefs
