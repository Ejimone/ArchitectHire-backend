from django.urls import path

from .views import MePreferencesView, MeRoleView, MeView

app_name = "accounts"

urlpatterns = [
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/me/role/", MeRoleView.as_view(), name="me-role"),
    path("auth/me/preferences/", MePreferencesView.as_view(), name="me-preferences"),
]
