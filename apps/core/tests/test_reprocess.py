"""Re-encoding images that entered storage before the fields normalised uploads.

The case this exists for is concrete: a 2048x2048 JPEG stored at 3.3 MB, which Vercel's
optimiser refuses to touch and serves to every visitor as-is. Through the pipeline it is
139 KB.
"""

import io

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from PIL import Image

from apps.cms.models import CaseCard, HeroCarouselSlide
from apps.core import reprocess


def a_big_jpeg(edge: int = 900) -> bytes:
    """A JPEG that is large in bytes without being large in pixels — quality 100 noise,
    which is exactly the shape of the file in production."""
    import random

    random.seed(7)
    image = Image.new("RGB", (edge, edge))
    image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(edge * edge)
        ]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=100)
    return buffer.getvalue()


@pytest.mark.django_db
class TestReprocessOversized:
    def _slide(self, data: bytes, name="slide.jpg", scope="landing", caption="QA"):
        slide, _ = HeroCarouselSlide.objects.get_or_create(scope=scope, caption=caption)
        # `.save()` on the field would re-encode on the way in — the whole point is to
        # simulate a file that got in before the field did that.
        slide.image.storage.save(f"cms/carousel/{name}", ContentFile(data))
        HeroCarouselSlide.objects.filter(pk=slide.pk).update(image=f"cms/carousel/{name}")
        slide.refresh_from_db()
        return slide

    def test_an_oversized_image_is_re_encoded(self):
        data = a_big_jpeg()
        slide = self._slide(data, name="oversized.jpg")
        assert slide.image.size == len(data)

        shrunk, saved = reprocess.reprocess_oversized(threshold=len(data) - 1)

        slide.refresh_from_db()
        assert shrunk == 1
        assert saved > 0
        assert slide.image.name.endswith(".webp")
        assert slide.image.size < len(data)

    def test_a_file_already_under_the_threshold_is_left_alone(self):
        slide = self._slide(a_big_jpeg(), name="fine.jpg")
        before = slide.image.name

        assert reprocess.reprocess_oversized(threshold=10_000_000) == (0, 0)

        slide.refresh_from_db()
        assert slide.image.name == before

    def test_dry_run_reports_without_writing(self, capsys):
        data = a_big_jpeg()
        slide = self._slide(data, name="dry.jpg")

        call_command("reprocess_images", "--threshold", str(len(data) - 1), "--dry-run")

        slide.refresh_from_db()
        assert slide.image.name == "cms/carousel/dry.jpg"
        assert "would shrink 1 image(s)" in capsys.readouterr().out

    def test_rows_sharing_a_file_are_updated_together(self):
        """Seeded photography is deliberately shared — one portrait, forty testimonials.
        Re-encoding per row would upload forty copies of the same picture."""
        data = a_big_jpeg()
        first = self._slide(data, name="shared.jpg", caption="QA one")
        second, _ = HeroCarouselSlide.objects.get_or_create(scope="landing", caption="QA two")
        HeroCarouselSlide.objects.filter(pk=second.pk).update(image="cms/carousel/shared.jpg")

        shrunk, _ = reprocess.reprocess_oversized(threshold=len(data) - 1)

        first.refresh_from_db()
        second.refresh_from_db()
        # One *file* re-encoded, both rows repointed at it.
        assert shrunk == 1
        assert first.image.name == second.image.name
        assert first.image.name.endswith(".webp")

    def test_a_file_missing_from_storage_is_reported_and_skipped(self, caplog):
        data = a_big_jpeg()
        slide = self._slide(data, name="gone.jpg")
        slide.image.storage.delete(slide.image.name)

        reprocess.reprocess_oversized(threshold=len(data) - 1)

        # A row pointing at a deleted object is a pre-existing problem, not a reason to
        # abandon the pass.
        assert "cms/carousel/gone.jpg" in caplog.text
        slide.refresh_from_db()
        assert slide.image.name == "cms/carousel/gone.jpg"

    def test_an_image_the_pipeline_declines_is_left_alone(self):
        """`process_image` returns its input for a GIF (re-encoding flattens the
        animation) — and a file it hands back unchanged is not an improvement."""
        buffer = io.BytesIO()
        Image.new("RGB", (400, 400), (200, 30, 30)).save(buffer, format="GIF")
        gif = buffer.getvalue()
        slide = self._slide(gif, name="animation.gif")

        reprocess.reprocess_oversized(threshold=len(gif) - 1)

        slide.refresh_from_db()
        assert slide.image.name == "cms/carousel/animation.gif"

    def test_only_normalised_columns_are_touched(self):
        """A plain FileField may hold a PDF deliverable; re-encoding one corrupts it."""
        columns = {
            (model.__name__, field.name) for model, field in reprocess.processed_image_columns()
        }
        assert ("HeroCarouselSlide", "image") in columns
        assert ("CaseCard", "image") in columns
        assert not any(name == "Deliverable" for name, _ in columns)

    def test_the_command_reports_what_it_shrank(self, capsys):
        data = a_big_jpeg()
        self._slide(data, name="reported.jpg")

        call_command("reprocess_images", "--threshold", str(len(data) - 1))

        assert "shrank 1 image(s)" in capsys.readouterr().out


@pytest.mark.django_db
def test_production_shaped_file_shrinks_by_an_order_of_magnitude():
    """The regression this module was written for: 2048x2048, quality 100."""
    data = a_big_jpeg(edge=2048)
    card, _ = CaseCard.objects.get_or_create(scope="landing", title="QA oversized card")
    card.image.storage.save("cms/case-cards/huge.jpg", ContentFile(data))
    CaseCard.objects.filter(pk=card.pk).update(image="cms/case-cards/huge.jpg")

    shrunk, saved = reprocess.reprocess_oversized(threshold=1_000_000)

    card.refresh_from_db()
    assert shrunk >= 1
    assert card.image.size < len(data) / 2
