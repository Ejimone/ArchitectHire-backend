from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CmsConfig(AppConfig):
    name = "apps.cms"
    verbose_name = "Site content"

    def ready(self):
        from apps.core.signals import register_content_version_bump

        register_content_version_bump(self)

        # Keep the Media assets list mirroring the site: saving/deleting a city,
        # project type, gallery card or city testimonial creates/prunes its
        # image-slot rows so the owner never types a slot key by hand.
        from django.apps import apps as global_apps

        def _sync_slots(sender, **kwargs):
            if kwargs.get("raw"):
                return
            from apps.cms.slots import sync_media_slots

            sync_media_slots()

        for label in (
            "jurisdictions.City",
            "catalog.ProjectType",
            "cms.CaseCard",
            "cms.Testimonial",
        ):
            model = global_apps.get_model(label)
            post_save.connect(
                _sync_slots, sender=model, weak=False, dispatch_uid=f"cms-slots-{label}"
            )
            post_delete.connect(
                _sync_slots, sender=model, weak=False, dispatch_uid=f"cms-slotsd-{label}"
            )
