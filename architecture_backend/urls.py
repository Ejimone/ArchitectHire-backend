from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts.webhooks import ClerkWebhookView
from apps.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/webhooks/clerk/", ClerkWebhookView.as_view(), name="clerk-webhook"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.engagements.urls")),
    path("api/v1/content/", include("apps.cms.urls")),
    path("api/v1/catalog/", include("apps.catalog.urls")),
    path("api/v1/providers/", include("apps.providers.urls")),
    path("api/v1/jurisdictions/", include("apps.jurisdictions.urls")),
]
