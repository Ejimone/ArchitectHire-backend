"""Give every record image a photograph on the deploy that ships this.

`seeds/records/` is a floor for images that live on a content row — case cards,
testimonial portraits, case-study heroes — the way `seeds/media/` has always been for
named slots. `manage.py seed --all` fills them, but a deploy that only runs `migrate`
would leave the site rendering crosshatch placeholders until someone remembered, so the
same idempotent filler runs here too.

Safe to run twice: it fills only rows whose image is empty, so it can never overwrite a
photograph the owner uploaded through the studio. Reversing it does nothing — removing
images from live rows to undo a migration would be the more destructive act.
"""

from django.db import migrations


def fill(apps, schema_editor):
    # The real models on purpose: this writes files through the storage backend and needs
    # `save()` to fire post_save so the caches purge. Historical models have neither.
    from apps.cms.record_media import attach_seed_record_images

    attach_seed_record_images()


class Migration(migrations.Migration):
    dependencies = [("cms", "0012_seedrun")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
