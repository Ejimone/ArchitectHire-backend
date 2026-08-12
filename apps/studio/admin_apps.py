"""The admin AppConfig.

Kept out of ``apps.py`` deliberately: Django scans a module for every AppConfig
subclass when resolving a bare ``"apps.studio"`` entry, and would refuse to choose
between this one, ``StudioConfig`` and the imported ``AdminConfig``. Referenced by
its full class path in INSTALLED_APPS, so Django imports it directly instead.
"""

from django.contrib.admin.apps import AdminConfig


class StudioAdminConfig(AdminConfig):
    """Replaces ``django.contrib.admin`` so ``admin.site`` is our own site.

    Unfold is installed as ``unfold.apps.BasicAppConfig`` precisely so it does not
    swap in its own site here and clobber ours.
    """

    default = False
    default_site = "apps.studio.sites.StudioAdminSite"
