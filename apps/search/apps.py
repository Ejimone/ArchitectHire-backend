from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "apps.search"
    verbose_name = "Search"

    def ready(self):
        from apps.core.signals import register_content_version_bump_for

        from .models import PopularSearch

        # Popular searches render on /search; the index itself is rebuilt by its own
        # command and never edited by hand, so only this model needs the purge wiring.
        register_content_version_bump_for(PopularSearch)
