"""Normalising uploaded images at the point they are stored.

**Division of labour.** The frontends put every CMS image through Next's
``/_next/image``, which already resizes per viewport, negotiates AVIF/WebP per browser
and caches the result at the edge. Generating a rendition set here would duplicate all of
that and go stale the moment a breakpoint changes. So this module does not make
renditions — it makes the *original* sane, which is the part Next cannot do for us:

* **Cap the dimensions.** Next fetches the original once per size variant. A 6000×4000
  phone photo costs that on every cold variant, and the pixels above ~2560px on the long
  edge are never displayed by any breakpoint the site has.
* **Strip metadata.** A photo straight off a phone or a DSLR carries EXIF, and EXIF
  carries GPS. An agency uploading photographs of clients' houses would otherwise publish
  the coordinates of those houses. This is the reason this module exists at all.
* **Re-encode.** The screenshots that make up much of the site's imagery arrive as PNG —
  the 1.1 MB hero carousel slide in production is one — and re-encode to a fraction of
  that as WebP with no visible loss.

Nothing here is allowed to lose an upload: every failure path keeps the file the user
actually chose. A corrupt or exotic image is worth serving unoptimised; it is not worth
a 500 in the admin.
"""

from __future__ import annotations

import io
import logging
from pathlib import PurePosixPath

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db import models

logger = logging.getLogger(__name__)

#: Longest edge kept, in pixels. Comfortably covers a full-bleed hero on a 2× display
#: (the widest `sizes` the site asks for is 100vw) with room for art-directed crops.
MAX_EDGE = 2560

#: WebP quality. 82 is the usual "no visible loss on photographs" point; screenshots and
#: flat colour survive it easily.
WEBP_QUALITY = 82

#: JPEG needs a little more to reach the same perceived quality as WebP at 82.
JPEG_QUALITY = 88

#: Formats left exactly as they are.
#:
#: GIF because re-encoding flattens an animation to its first frame, and ICO/SVG because
#: they are not photographic content. SVG never reaches here anyway — ImageField's own
#: validation rejects it — but naming it documents the intent.
PASSTHROUGH_FORMATS = {"GIF", "ICO", "SVG"}

#: Below this, re-encoding tends to *grow* the file: tiny PNGs of flat colour (logos,
#: icons) are already close to optimal and WebP's header is a bigger share of the total.
#: They still get their metadata stripped, because that is about privacy, not size.
MIN_REENCODE_PIXELS = 64 * 64


#: Target formats this module knows how to write, mapped to (extension, content type).
#: JPEG exists for one reason: link-preview crawlers. Facebook, LinkedIn, WhatsApp and
#: iMessage do not reliably render a WebP `og:image`, so an OG image re-encoded to WebP
#: is a link that previews as a blank card — the exact failure this project is fixing.
_FORMATS = {
    "WEBP": (".webp", "image/webp"),
    "JPEG": (".jpg", "image/jpeg"),
}


def process_image(file, *, max_edge: int = MAX_EDGE, to_format: str = "WEBP"):
    """Return a normalised copy of `file`, or `file` itself if it is best left alone.

    Returns the original on *any* problem — an unreadable image, a format Pillow cannot
    write, a result that came out bigger than what we started with. The caller stores
    whatever comes back, so the worst case is an unoptimised upload rather than a lost
    one.
    """
    extension, content_type = _FORMATS[to_format]
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        file.seek(0)
        with Image.open(file) as opened:
            source_format = (opened.format or "").upper()
            if source_format in PASSTHROUGH_FORMATS or getattr(opened, "is_animated", False):
                file.seek(0)
                return file

            # Honour the EXIF orientation flag *before* discarding EXIF, or a portrait
            # photo from a phone gets stored on its side.
            image = ImageOps.exif_transpose(opened)

            original_size = image.size
            if max(original_size) > max_edge:
                width, height = original_size
                scale = max_edge / max(width, height)
                image = image.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    resample=Image.Resampling.LANCZOS,
                )

            small = original_size[0] * original_size[1] < MIN_REENCODE_PIXELS
            if small and original_size == image.size and source_format == to_format:
                file.seek(0)
                return file

            # `has_transparency_data` covers palette images with a tRNS chunk as well as
            # RGBA/LA, so a transparent logo does not gain a black background. JPEG has
            # no alpha channel at all, so anything headed there is flattened onto white
            # rather than onto the black that a bare `convert("RGB")` would give it.
            keep_alpha = to_format == "WEBP" and image.has_transparency_data
            if keep_alpha:
                if image.mode != "RGBA":
                    image = image.convert("RGBA")
            elif image.mode != "RGB":
                if image.has_transparency_data:
                    from PIL import Image as _Image

                    flattened = _Image.new("RGB", image.size, (255, 255, 255))
                    flattened.paste(image.convert("RGBA"), mask=image.convert("RGBA"))
                    image = flattened
                else:
                    image = image.convert("RGB")

            buffer = io.BytesIO()
            # `Image.save` writes no EXIF/ICC/XMP unless handed one explicitly, so
            # simply not passing them through is the strip.
            if to_format == "JPEG":
                image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            else:
                image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # An unreadable or exotic image is not worth a 500 in the admin — store what the
        # user chose and let it through unoptimised. `seek` is safe here: the identical
        # call at the top of the block already succeeded on this same object.
        logger.warning("Leaving %s unprocessed: %s", getattr(file, "name", "<upload>"), exc)
        file.seek(0)
        return file

    size = buffer.tell()
    original_size_bytes = getattr(file, "size", None)
    # Re-encoding an already-efficient file can grow it. Keeping whichever is smaller
    # means enabling this can never make a page heavier than it was — but only when the
    # original is already in the target format, since otherwise we would be trading the
    # metadata strip and the dimension cap for a few kilobytes.
    if (
        original_size_bytes is not None
        and size >= original_size_bytes
        and source_format == to_format
        and original_size == image.size
    ):
        file.seek(0)
        return file

    buffer.seek(0)
    name = f"{PurePosixPath(getattr(file, 'name', 'image')).stem}{extension}"
    return InMemoryUploadedFile(
        buffer,
        field_name=getattr(file, "field_name", None),
        name=name,
        content_type=content_type,
        size=size,
        charset=None,
    )


class ProcessedImageField(models.ImageField):
    """An ImageField that normalises whatever is uploaded into it.

    Deliberately a field rather than a `post_save` signal: the transform has to happen
    *before* the file is written to storage, or the unprocessed original is uploaded to
    Spaces first and then orphaned there — paid for, never served, and still carrying the
    EXIF we meant to remove.

    `to_format="JPEG"` is for images consumed by something other than a browser — an
    `og:image` read by a link-preview crawler, most of all.
    """

    def __init__(self, *args, to_format: str = "WEBP", max_edge: int = MAX_EDGE, **kwargs):
        self.to_format = to_format
        self.max_edge = max_edge
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Only emit the non-defaults, so 16 of the 18 fields produce no migration noise.
        if self.to_format != "WEBP":
            kwargs["to_format"] = self.to_format
        if self.max_edge != MAX_EDGE:
            kwargs["max_edge"] = self.max_edge
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        file = getattr(model_instance, self.attname)
        # `_committed` is False only for a file that has just been assigned and not yet
        # written, which is exactly the new-upload case. Re-saving a row whose image is
        # unchanged must not re-encode it: repeated saves would compound WebP's loss.
        if file and not file._committed:
            processed = process_image(file.file, max_edge=self.max_edge, to_format=self.to_format)
            if processed is not file.file:
                file.save(processed.name, processed, save=False)
        return super().pre_save(model_instance, add)
