from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CmsConfig(AppConfig):
    name = "apps.cms"
    verbose_name = "Site content"

    def ready(self):
        from apps.core.cache import bump_content_version

        def _bump(sender, **kwargs):
            bump_content_version()

        for model in self.get_models():
            post_save.connect(
                _bump, sender=model, weak=False, dispatch_uid=f"cms-bump-{model.__name__}"
            )
            post_delete.connect(
                _bump, sender=model, weak=False, dispatch_uid=f"cms-bumpd-{model.__name__}"
            )
