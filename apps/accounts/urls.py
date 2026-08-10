from django.urls import path

from .views import MePreferencesView, MeView

app_name = "accounts"

urlpatterns = [
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/me/preferences/", MePreferencesView.as_view(), name="me-preferences"),
]
