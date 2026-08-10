from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    verbose_name = "Catalog"

    def ready(self):
        from apps.core.signals import register_content_version_bump

        register_content_version_bump(self)
