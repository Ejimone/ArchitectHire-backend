"""Re-encode images that entered storage before `ProcessedImageField` guarded the door.

Every CMS image column is a `ProcessedImageField` today: an upload is capped at 2560 px,
stripped of EXIF and written as WebP before it ever reaches storage. The fields were
plain `ImageField`s once, and what went in then is still there.

One of those is a 2048x2048 JPEG at **3.3 MB** — the same picture is ~200 KB as WebP.
Vercel's optimiser refuses a source that large and hands the browser the original
untouched, so it is not merely a slow image, it is 3.3 MB delivered to every visitor of
`/projects`, phones included.

Three rules, each one a decision:

* **Only `ProcessedImageField` columns.** A plain `FileField` may hold a PDF deliverable
  or a credential scan; re-encoding those would corrupt them.
* **Keyed on the storage name, not the row.** Seeded photography is deliberately shared —
  one portrait serves forty testimonials — so a file is re-encoded once and every row
  that points at it is updated together. Re-encoding per row would upload forty copies.
* **The original is never deleted.** It is what a rollback restores from, and it costs
  cents. The rows stop referencing it; that is enough.
"""

import logging

from django.apps import apps as django_apps
from django.core.files.base import ContentFile

from apps.core.images import ProcessedImageField, process_image

logger = logging.getLogger(__name__)

#: Above this, a stored image is worth re-encoding. Comfortably above a 2560 px WebP
#: photograph (the largest in production is ~610 KB), so a file over it did not come
#: through the current pipeline.
OVERSIZE_BYTES = 1_000_000


def processed_image_columns():
    """`(model, field)` for every column that promises normalised images."""
    for model in django_apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, ProcessedImageField):
                yield model, field


def reprocess_oversized(*, threshold: int = OVERSIZE_BYTES, dry_run: bool = False):
    """Re-encode stored images larger than `threshold`. Returns `(shrunk, saved_bytes)`."""
    shrunk = 0
    saved = 0
    #: old storage name → new one, so a shared file is re-encoded once.
    replaced: dict[str, str] = {}

    for model, field in processed_image_columns():
        rows = model._default_manager.exclude(**{field.name: ""})
        for obj in rows.iterator():
            stored = getattr(obj, field.name)
            if stored.name in replaced:
                setattr(obj, field.name, replaced[stored.name])
                obj.save()
                continue

            try:
                size = stored.size
            except Exception:  # noqa: BLE001 — any storage's "it is not there"
                logger.warning("reprocess: %s is missing from storage", stored.name)
                continue
            if size <= threshold:
                continue

            with stored.open("rb") as handle:
                data = handle.read()
            # A `ContentFile` rather than the `FieldFile` itself: `process_image` seeks
            # its input twice, and a file streamed from object storage does not always
            # rewind.
            source = ContentFile(data, name=stored.name.rsplit("/", 1)[-1])
            processed = process_image(source, max_edge=field.max_edge, to_format=field.to_format)
            if processed is source or processed.size >= size:
                # `process_image` declines what is already optimal, and a re-encode that
                # grows the file is not an improvement worth a new object in storage.
                continue

            if dry_run:
                shrunk += 1
                saved += size - processed.size
                continue

            old_name = stored.name
            stored.save(processed.name, processed, save=False)
            obj.save()
            replaced[old_name] = getattr(obj, field.name).name
            shrunk += 1
            saved += size - processed.size

    return shrunk, saved
