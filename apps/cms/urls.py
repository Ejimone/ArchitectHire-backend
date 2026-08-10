from django.urls import path

from .views import FooterView, MediaSlotsView, NavigationView, PageContentView, SettingsView

app_name = "cms"

urlpatterns = [
    path("pages/<str:page_key>/", PageContentView.as_view(), name="page"),
    path("nav/", NavigationView.as_view(), name="nav"),
    path("footer/", FooterView.as_view(), name="footer"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("media/", MediaSlotsView.as_view(), name="media"),
]
