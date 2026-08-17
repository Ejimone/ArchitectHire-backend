"""Upload normalisation: dimension cap, metadata strip, re-encode."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.cms.models import MediaAsset, PageSEO
from apps.core.images import MAX_EDGE, ProcessedImageField, process_image

#: EXIF tag numbers, so the tests need no extra dependency to build a realistic photo.
_MAKE = 0x010F
_ORIENTATION = 0x0112
_GPS_IFD = 0x8825


def _upload(name="shot.png", *, size=(80, 60), colour=(120, 140, 200), fmt="PNG", **save_kwargs):
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format=fmt, **save_kwargs)
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


def _opened(result):
    result.seek(0)
    return Image.open(result)


class TestProcessImage:
    def test_a_png_becomes_a_smaller_webp(self):
        source = _upload(size=(1200, 800))
        result = process_image(source)

        assert result is not source
        assert result.name.endswith(".webp")
        assert result.content_type == "image/webp"
        assert result.size < source.size
        assert _opened(result).format == "WEBP"

    def test_oversized_images_are_capped_on_the_long_edge(self):
        result = process_image(_upload(size=(MAX_EDGE * 2, MAX_EDGE)))
        image = _opened(result)

        assert max(image.size) == MAX_EDGE
        assert image.size == (MAX_EDGE, MAX_EDGE // 2)  # aspect ratio preserved

    def test_images_within_the_cap_keep_their_dimensions(self):
        assert _opened(process_image(_upload(size=(900, 300)))).size == (900, 300)

    def test_transparency_survives(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (200, 200), (255, 0, 0, 0)).save(buffer, format="PNG")
        buffer.seek(0)
        source = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")

        image = _opened(process_image(source))
        assert image.mode == "RGBA"
        assert image.getpixel((100, 100))[3] == 0  # still fully transparent

    def test_animated_gifs_are_left_alone(self):
        buffer = io.BytesIO()
        frames = [Image.new("P", (40, 40), i) for i in range(3)]
        frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
        buffer.seek(0)
        source = SimpleUploadedFile("spin.gif", buffer.getvalue(), content_type="image/gif")

        assert process_image(source) is source

    def test_an_unreadable_file_is_stored_as_uploaded(self):
        """A broken upload must not 500 the admin — store it and move on."""
        source = SimpleUploadedFile("nope.png", b"this is not an image", content_type="image/png")
        assert process_image(source) is source

    def test_a_tiny_webp_is_not_rewritten(self):
        source = _upload("icon.webp", size=(32, 32), fmt="WEBP")
        assert process_image(source) is source

    def test_an_efficient_webp_is_kept_when_re_encoding_would_grow_it(self):
        """Enabling this pipeline must never make a page heavier than it was."""
        source = _upload("photo.webp", size=(300, 300), fmt="WEBP", quality=20)
        assert process_image(source) is source


class TestMetadataStripping:
    def _with_gps(self):
        """A JPEG carrying GPS coordinates, as a phone or DSLR would produce."""
        exif = Image.Exif()
        exif[_MAKE] = "QA Camera"
        gps = exif.get_ifd(_GPS_IFD)
        gps[1], gps[2] = "N", (37.0, 46.0, 0.0)
        gps[3], gps[4] = "W", (122.0, 25.0, 0.0)

        buffer = io.BytesIO()
        Image.new("RGB", (400, 300), (90, 90, 90)).save(buffer, format="JPEG", exif=exif)
        buffer.seek(0)
        return SimpleUploadedFile("house.jpg", buffer.getvalue(), content_type="image/jpeg")

    def test_gps_coordinates_do_not_survive(self):
        """The reason this pipeline exists: an agency uploading photographs of clients'
        houses must not publish the coordinates of those houses."""
        source = self._with_gps()
        source.seek(0)
        assert dict(Image.open(source).getexif().get_ifd(_GPS_IFD))  # precondition

        result = _opened(process_image(source))
        assert not dict(result.getexif())
        assert "exif" not in result.info

    def test_orientation_is_applied_before_exif_is_discarded(self):
        """Dropping EXIF without honouring its orientation flag would leave a portrait
        photo from a phone stored on its side."""
        exif = Image.Exif()
        exif[_ORIENTATION] = 6  # rotate 90° clockwise

        buffer = io.BytesIO()
        Image.new("RGB", (400, 200), (10, 20, 30)).save(buffer, format="JPEG", exif=exif)
        buffer.seek(0)
        source = SimpleUploadedFile("rot.jpg", buffer.getvalue(), content_type="image/jpeg")

        assert _opened(process_image(source)).size == (200, 400)  # swapped, as intended


class TestTargetFormat:
    def test_og_images_are_jpeg_because_crawlers_do_not_render_webp(self):
        result = process_image(_upload(size=(1200, 630)), to_format="JPEG")

        assert result.name.endswith(".jpg")
        assert result.content_type == "image/jpeg"
        assert _opened(result).format == "JPEG"

    def test_a_palette_png_with_transparency_keeps_its_alpha_as_webp(self):
        """Palette images carry transparency in a tRNS chunk rather than an alpha band,
        so mode alone ("P") does not reveal it — hence `has_transparency_data`."""
        image = Image.new("P", (120, 120), 1)
        image.putpalette([0, 0, 0] * 256)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", transparency=1)
        buffer.seek(0)
        source = SimpleUploadedFile("badge.png", buffer.getvalue(), content_type="image/png")

        converted = _opened(process_image(source))
        assert converted.mode == "RGBA"
        assert converted.getpixel((60, 60))[3] == 0

    def test_a_greyscale_photo_is_converted_for_jpeg(self):
        buffer = io.BytesIO()
        Image.new("L", (300, 200), 128).save(buffer, format="PNG")
        buffer.seek(0)
        source = SimpleUploadedFile("grey.png", buffer.getvalue(), content_type="image/png")

        converted = _opened(process_image(source, to_format="JPEG"))
        assert converted.mode == "RGB"
        assert converted.format == "JPEG"

    def test_transparency_is_flattened_onto_white_for_jpeg(self):
        """`convert("RGB")` alone would composite onto black and blacken a logo."""
        buffer = io.BytesIO()
        Image.new("RGBA", (100, 100), (255, 255, 255, 0)).save(buffer, format="PNG")
        buffer.seek(0)
        source = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")

        image = _opened(process_image(source, to_format="JPEG"))
        assert image.mode == "RGB"
        assert image.getpixel((50, 50)) == (255, 255, 255)


@pytest.mark.django_db
class TestProcessedImageField:
    def test_uploading_through_a_model_stores_the_processed_file(self):
        asset = MediaAsset.objects.create(slot_key="landing:qa-processed")
        asset.image = _upload("hero.png", size=(3200, 1800))
        asset.save()

        asset.refresh_from_db()
        assert asset.image.name.endswith(".webp")
        with Image.open(asset.image) as stored:
            assert max(stored.size) == MAX_EDGE
            assert stored.format == "WEBP"

    def test_re_saving_an_unchanged_row_does_not_re_encode(self):
        """Re-encoding on every save would compound WebP's loss over an image's life."""
        asset = MediaAsset.objects.create(slot_key="landing:qa-stable")
        asset.image = _upload("hero.png", size=(900, 600))
        asset.save()
        first_name = asset.image.name

        asset.alt_text = "edited"
        asset.save()

        asset.refresh_from_db()
        assert asset.image.name == first_name  # no second file written

    def test_og_image_field_writes_jpeg(self):
        # `page_key` is unique and the studio suite commits, so rows from other tests
        # can still be present — take whichever row exists rather than insisting on one.
        seo, _ = PageSEO.objects.get_or_create(page_key="landing", defaults={"title": "QA"})
        seo.og_image = _upload("card.png", size=(1200, 630))
        seo.save()

        seo.refresh_from_db()
        assert seo.og_image.name.endswith(".jpg")

    def test_deconstruct_only_emits_non_default_options(self):
        """Keeps the migration for 16 of the 18 fields free of redundant kwargs."""
        _, _, _, plain = ProcessedImageField(upload_to="x/").deconstruct()
        assert "to_format" not in plain and "max_edge" not in plain

        _, _, _, custom = ProcessedImageField(
            upload_to="x/", to_format="JPEG", max_edge=800
        ).deconstruct()
        assert custom["to_format"] == "JPEG"
        assert custom["max_edge"] == 800

    def test_max_edge_override_is_honoured(self):
        field = ProcessedImageField(upload_to="x/", max_edge=100)
        assert field.max_edge == 100
        assert max(_opened(process_image(_upload(size=(500, 400)), max_edge=100)).size) == 100
