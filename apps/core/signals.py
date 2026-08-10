"""Shared helper: wire an app's models to bump the CMS content version on write.

Marketing pages read from cms, catalog and jurisdictions; a write to any of them
must invalidate cached page payloads.
"""

from django.db.models.signals import post_delete, post_save

from apps.core.cache import bump_content_version


def register_content_version_bump(app_config):
    def _bump(sender, **kwargs):
        bump_content_version()

    for model in app_config.get_models():
        post_save.connect(_bump, sender=model, weak=False, dispatch_uid=f"bump-{model.__name__}")
        post_delete.connect(_bump, sender=model, weak=False, dispatch_uid=f"bumpd-{model.__name__}")
