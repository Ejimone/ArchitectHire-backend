"""Re-encode the images that entered storage before the fields normalised uploads.

Production carries one 2048x2048 JPEG at 3.3 MB. Vercel's optimiser refuses a source
that large and hands the browser the original untouched, so every visitor to /projects
downloads 3.3 MB — phones included. Through the same pipeline every upload goes through
today it is 139 KB, measured on that exact file.

Here rather than only in a management command because a deploy is a `git push`: the hook
on the VM rebuilds and restarts, and the container runs `migrate` on start. A fix that
needs someone to remember an SSH session is a fix that does not happen.

Reversing does nothing on purpose. The originals are still in storage — the rows simply
stop pointing at them — so a rollback is restoring the previous names, not re-inflating
the files.
"""

from django.db import migrations


def shrink(apps, schema_editor):
    # The real models: this reads and writes through the storage backend and needs
    # `save()` to fire post_save so the frontend caches purge.
    from apps.core.reprocess import reprocess_oversized

    reprocess_oversized()


class Migration(migrations.Migration):
    dependencies = [("cms", "0013_seed_record_images")]

    operations = [migrations.RunPython(shrink, migrations.RunPython.noop)]
