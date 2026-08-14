"""Shared helper: wire models to bump the CMS content version on write.

Marketing pages read from cms, catalog and jurisdictions; a write to any of them must
invalidate cached page payloads. One implementation, used by every app that has
content — a second inline copy in an AppConfig is exactly how `payments` came to be
missed for as long as it was.
"""

from django.db.models.signals import post_delete, post_save

from apps.core.cache import bump_content_version
from apps.core.tags import tags_for


def _bump(sender, instance, **kwargs):
    # `raw` means loaddata: the fixture is replaying content that is already live, and
    # bumping per row would turn a restore into thousands of purges.
    if kwargs.get("raw"):
        return
    bump_content_version(tags_for(instance))


def register_content_version_bump_for(model):
    """Purge the pages `model` feeds whenever one of its rows is written."""
    label = model._meta.label
    post_save.connect(_bump, sender=model, weak=False, dispatch_uid=f"bump-{label}")
    post_delete.connect(_bump, sender=model, weak=False, dispatch_uid=f"bumpd-{label}")


def register_content_version_bump(app_config):
    """The same, for every model in an app whose tables are all content."""
    for model in app_config.get_models():
        register_content_version_bump_for(model)
