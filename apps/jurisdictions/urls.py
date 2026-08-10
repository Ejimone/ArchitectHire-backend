from django.urls import path

from .views import CitiesView, CityDetailView, StateDetailView, StatesView

app_name = "jurisdictions"

urlpatterns = [
    path("states/", StatesView.as_view(), name="states"),
    path("states/<str:code>/", StateDetailView.as_view(), name="state-detail"),
    path("cities/", CitiesView.as_view(), name="cities"),
    path("cities/<slug:slug>/", CityDetailView.as_view(), name="city-detail"),
]
