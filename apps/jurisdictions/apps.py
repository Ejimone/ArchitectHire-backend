from django.apps import AppConfig


class JurisdictionsConfig(AppConfig):
    name = "apps.jurisdictions"
    verbose_name = "Jurisdictions"

    def ready(self):
        from apps.core.signals import register_content_version_bump

        register_content_version_bump(self)
