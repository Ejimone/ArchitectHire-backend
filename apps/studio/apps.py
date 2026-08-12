from django.apps import AppConfig


class StudioConfig(AppConfig):
    """The Studio admin UI: templates, static assets, custom pages. No models."""

    name = "apps.studio"
    verbose_name = "Studio"
