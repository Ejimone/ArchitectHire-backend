from django.apps import AppConfig


class StudioApiConfig(AppConfig):
    """JSON API behind the visual Studio.

    Deliberately not registered with `register_content_version_bump`: nothing here is
    rendered content, and a draft being staged must not purge the live site's caches.
    Publishing does that, by saving the real rows.
    """

    name = "apps.studio_api"
    verbose_name = "Studio API"
