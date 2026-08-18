"""What the Studio will accept as an image upload.

Two checks, both cheap, both before a byte reaches storage:

* **Size** — `STUDIO_MAX_UPLOAD_BYTES`. The upload endpoints buffer the whole file to
  normalise it, so an unbounded upload is an unbounded memory allocation on a small box.
* **Content** — Pillow must be able to identify it as one of the raster formats the site
  can serve. That rejects SVG (a script vector, not a photo), PDFs and executables
  renamed `.jpg`, and truncated files that would 500 later inside `process_image`.
  GIF is allowed because `process_image` deliberately passes animations through.
"""

from django.conf import settings
from PIL import Image, UnidentifiedImageError

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF", "AVIF", "HEIF"})


class UploadRejected(Exception):
    """Surfaced to the client as a 400 with this message."""


def validate_upload(upload) -> str:
    """Raise `UploadRejected` unless `upload` is an acceptable image. Returns the format."""
    limit = settings.STUDIO_MAX_UPLOAD_BYTES
    if upload.size > limit:
        raise UploadRejected(
            f"That file is {upload.size / (1024 * 1024):.1f} MB; the limit is "
            f"{limit // (1024 * 1024)} MB. Export a smaller copy and try again."
        )
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            fmt = (image.format or "").upper()
            # `verify()` walks the file without decoding pixels; a truncated or corrupt
            # image raises here instead of deep inside the resize later.
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UploadRejected(
            "That file is not an image the site can display. Upload a JPEG, PNG, WebP or GIF."
        ) from exc
    finally:
        upload.seek(0)
    if fmt not in ALLOWED_FORMATS:
        raise UploadRejected(
            f"{fmt or 'That format'} is not supported. Upload a JPEG, PNG, WebP or GIF."
        )
    return fmt
