from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.accounts.webhooks import ClerkWebhookView
from apps.core.views import health
from apps.payments.views import StripeWebhookView

urlpatterns = [
    # Opening the deployment URL used to land on a bare "Not Found" page, because this
    # server has routes for /admin/ and /api/ and nothing at the root. The only person
    # who ever types the bare API host is the owner, and what they want is the admin.
    #
    # 302 rather than 301: a permanent redirect is cached by browsers effectively
    # forever, so if the root is ever given a real page, everyone who visited it before
    # would keep being bounced to /admin/ with no way to clear it but their own cache.
    path("", RedirectView.as_view(url="/admin/", permanent=False), name="root"),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/webhooks/clerk/", ClerkWebhookView.as_view(), name="clerk-webhook"),
    path("api/webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.projects.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.engagements.urls")),
    path("api/v1/payments/", include("apps.payments.urls")),
    path("api/v1/", include("apps.messaging.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/content/", include("apps.cms.urls")),
    path("api/v1/catalog/", include("apps.catalog.urls")),
    path("api/v1/providers/", include("apps.providers.urls")),
    path("api/v1/jurisdictions/", include("apps.jurisdictions.urls")),
    path("api/v1/studio/", include("apps.studio_api.urls")),
]

# Serve uploaded media locally. In production DigitalOcean Spaces serves it
# directly (see STORAGES in settings/prod.py), so this only applies in dev —
# without it, every image the owner uploads in Django admin 404s.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
