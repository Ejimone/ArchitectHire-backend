import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


@pytest.fixture
def image_upload():
    """A real (tiny) PNG — ImageField validation rejects arbitrary bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (120, 90, 40)).save(buffer, format="PNG")
    return SimpleUploadedFile("slot.png", buffer.getvalue(), content_type="image/png")


@pytest.fixture
def clean_content(db):
    """An empty content set, for tests that assert on site-wide totals.

    Studio's screens report aggregates — "3 of 47 slots filled", "2 items in draft" —
    so they cannot assume a pristine database. The messaging suite runs with
    `transaction=True`, which commits, and `CmsConfig.ready()` wires
    `sync_media_slots()` onto City/ProjectType/CaseCard saves, so rows created
    elsewhere do reach these tests.

    Deliberately not autouse: it is slow enough to matter across the ~140
    parametrised admin-render tests, which do not care about totals.
    """
    from apps.cms.models import CopyBlock, MediaAsset, PageSEO
    from apps.studio.publishing import publishable_models

    # Order matters: deleting a CaseCard or Testimonial fires the post_delete hook
    # that re-runs sync_media_slots(), which would recreate the MediaAsset rows.
    for model in publishable_models():
        model._default_manager.all().delete()
    # The remaining content models are not publishable, so the loop above misses
    # them — and slot_key/page_key are unique, so a leftover row breaks create().
    MediaAsset.objects.all().delete()
    PageSEO.objects.all().delete()
    CopyBlock.objects.all().delete()
