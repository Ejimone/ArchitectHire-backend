"""The seeded floor for images that live on a content row.

`test_media_slots.py` covers the same contract for named `MediaAsset` slots. This file
covers the per-row columns — a case card's photo, a case study's hero, a testimonial's
portrait — which had no floor at all until a fresh install rendered every project card as
a crosshatch placeholder on the live site.
"""

import json

import pytest
from PIL import Image

from apps.cms import models as cms  # `Testimonial` imported bare reads as a test class
from apps.cms import record_media
from apps.cms.models import CaseCard, Persona
from apps.cms.models_editorial import CaseStudy, CaseStudyImage


@pytest.mark.django_db
class TestPools:
    """Which photograph a row gets is decided by the words in its own title."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("garage-conversion-into-an-adu", "adu"),
            ("a-full-gut-kitchen-bath", "kitchen"),
            ("primary-bath-refit", "bathroom"),
            ("retail-to-restaurant-change-of-use", "commercial"),
            ("second-story-addition", "addition"),
            ("rear-extension-hillside", "addition"),
            ("whole-home-renovation", "living"),
            ("a-ground-up-custom-home", "exterior"),
            ("how-much-does-a-permit-cost", "drafting"),
            ("how-to-hire-an-architect", "site"),
        ],
    )
    def test_a_slug_picks_its_subject(self, text, expected):
        assert record_media._slug_pool(text) == expected

    def test_an_unrecognised_slug_falls_back_to_the_default(self):
        assert record_media._slug_pool("something-else") == "exterior"
        assert record_media._slug_pool("something-else", default="site") == "site"

    def test_a_card_scope_can_override_the_title(self):
        spec = record_media.SPEC_BY_LABEL["cms.casecard"]
        assert spec.pool(CaseCard(scope="cad-drafting", title="Kitchen remodel")) == "portrait"
        assert spec.pool(CaseCard(scope="3d-visualization", title="Kitchen remodel")) == "render"
        assert spec.pool(CaseCard(scope="landing", title="Kitchen remodel")) == "kitchen"

    def test_a_persona_is_a_portrait_unless_it_is_a_collection_cover(self):
        spec = record_media.SPEC_BY_LABEL["cms.persona"]
        assert spec.pool(Persona(scope="about", title="Maya")) == "portrait"
        assert spec.pool(Persona(scope="inspiration", title="Kitchen collection")) == "kitchen"

    def test_only_scopes_that_draw_a_portrait_are_seeded(self):
        spec = record_media.SPEC_BY_LABEL["cms.persona"]
        assert spec.renders(Persona(scope="about", title="Maya")) is True
        # Service-variant personas are a text block: nothing renders their image column,
        # so seeding one would cost bytes for a picture nobody can ever see.
        assert spec.renders(Persona(scope="services", title="Fixed fee")) is False

    def test_a_carousel_slide_follows_the_page_it_is_on(self):
        spec = record_media.SPEC_BY_LABEL["cms.herocarouselslide"]
        model = spec.model
        assert spec.pool(model(scope="cities", caption="")) == "city"
        assert spec.pool(model(scope="unmapped", caption="")) == "exterior"

    def test_a_child_row_is_keyed_through_its_parent(self, db):
        study = CaseStudy.objects.create(slug="a-garage-adu", title="A garage ADU")
        shot = CaseStudyImage.objects.create(case_study=study, sort_order=2)
        spec = record_media.SPEC_BY_LABEL["cms.casestudyimage"]
        # Natural keys, never pks: the same row has a different pk on every machine.
        assert record_media._key_for(spec, shot) == "cms.casestudyimage|a-garage-adu|2"
        assert spec.pool(shot) == "adu"


@pytest.mark.django_db
class TestAttachSeedRecordImages:
    """Filling empty columns without ever touching one the owner has set."""

    def _manifest(self, tmp_path, monkeypatch, *, entries=None, write_file=True):
        seed_dir = tmp_path / "records"
        seed_dir.mkdir()
        if write_file:
            Image.new("RGB", (40, 30), (10, 120, 80)).save(seed_dir / "sample.webp", format="WEBP")
        manifest = seed_dir / "manifest.json"
        default = {"cms.casecard|landing|QA project": {"file": "sample.webp", "pool": "exterior"}}
        manifest.write_text(json.dumps(default if entries is None else entries))
        monkeypatch.setattr(record_media, "SEED_DIR", seed_dir)
        monkeypatch.setattr(record_media, "MANIFEST", manifest)
        return seed_dir

    def _card(self, title="QA project", **kwargs):
        card, _ = CaseCard.objects.get_or_create(
            scope="landing", title=title, defaults={"image": "", **kwargs}
        )
        CaseCard.objects.filter(pk=card.pk).update(image=kwargs.get("image", ""))
        card.refresh_from_db()
        return card

    def test_an_empty_column_is_filled(self, tmp_path, monkeypatch):
        card = self._card()
        self._manifest(tmp_path, monkeypatch)

        filled, skipped = record_media.attach_seed_record_images()

        assert (filled, skipped) == (1, 0)
        card.refresh_from_db()
        assert card.image.name.endswith(".webp")
        assert card.image.storage.exists(card.image.name)

    def test_a_photograph_the_owner_uploaded_is_never_overwritten(self, tmp_path, monkeypatch):
        card = self._card(image="cms/case-cards/owners-own.webp")
        self._manifest(tmp_path, monkeypatch)

        assert record_media.attach_seed_record_images() == (0, 1)

        card.refresh_from_db()
        assert card.image.name == "cms/case-cards/owners-own.webp"

    def test_overwrite_is_available_when_asked_for_explicitly(self, tmp_path, monkeypatch):
        card = self._card(image="cms/case-cards/owners-own.webp")
        self._manifest(tmp_path, monkeypatch)

        filled, skipped = record_media.attach_seed_record_images(overwrite=True)

        assert (filled, skipped) == (1, 0)
        card.refresh_from_db()
        assert card.image.name != "cms/case-cards/owners-own.webp"

    def test_a_row_the_manifest_does_not_mention_is_left_alone(self, tmp_path, monkeypatch):
        card = self._card(title="Not in the manifest")
        self._manifest(tmp_path, monkeypatch)

        record_media.attach_seed_record_images()

        card.refresh_from_db()
        assert card.image.name == ""

    def test_a_missing_file_is_skipped_rather_than_erroring(self, tmp_path, monkeypatch):
        self._card()
        self._manifest(tmp_path, monkeypatch, write_file=False)

        assert record_media.attach_seed_record_images() == (0, 0)

    def test_no_manifest_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(record_media, "MANIFEST", tmp_path / "absent.json")
        assert record_media.attach_seed_record_images() == (0, 0)

    def test_rows_sharing_a_photograph_share_the_file(self, tmp_path, monkeypatch):
        first = self._card(title="QA project")
        second = self._card(title="QA project two")
        self._manifest(
            tmp_path,
            monkeypatch,
            entries={
                "cms.casecard|landing|QA project": {"file": "sample.webp", "pool": "exterior"},
                "cms.casecard|landing|QA project two": {"file": "sample.webp", "pool": "exterior"},
            },
        )

        filled, _ = record_media.attach_seed_record_images()

        assert filled == 2
        first.refresh_from_db()
        second.refresh_from_db()
        # One upload, two rows: a portrait pool spread over forty testimonials must not
        # put forty copies of the same photograph in the object store.
        assert first.image.name == second.image.name

    def test_it_writes_through_save_so_the_live_site_is_purged(self, tmp_path, monkeypatch):
        """`.update()` would be faster and would leave the site serving placeholders."""
        self._card()
        self._manifest(tmp_path, monkeypatch)
        seen = []
        from django.db.models.signals import post_save

        def spy(sender, instance, **kwargs):
            seen.append(instance.pk)

        post_save.connect(spy, sender=CaseCard)
        try:
            record_media.attach_seed_record_images()
        finally:
            post_save.disconnect(spy, sender=CaseCard)

        assert seen, "post_save never fired — bump_content_version would not have run"

    def test_only_empty_rows_are_enumerated_unless_asked_otherwise(self, tmp_path, monkeypatch):
        self._card(image="cms/case-cards/owners-own.webp")
        keys = {key for key, _, _ in record_media.expected_record_images()}
        assert "cms.casecard|landing|QA project" not in keys
        keys = {key for key, _, _ in record_media.expected_record_images(only_empty=False)}
        assert "cms.casecard|landing|QA project" in keys

    def test_a_row_that_renders_no_image_is_never_enumerated(self):
        Persona.objects.create(scope="services", title="Fixed fee", body="…")
        Persona.objects.create(scope="about", title="Maya", body="…")
        titles = {key.split("|")[-1] for key, _, _ in record_media.expected_record_images()}
        assert "Maya" in titles
        assert "Fixed fee" not in titles

    def test_a_row_the_owner_filled_is_reported_as_skipped(self, tmp_path, monkeypatch):
        self._card(image="cms/case-cards/owners-own.webp")
        self._manifest(tmp_path, monkeypatch)

        assert record_media.attach_seed_record_images() == (0, 1)


@pytest.mark.django_db
class TestCommittedManifest:
    """The manifest in the repository has to match the files beside it."""

    def test_every_entry_points_at_a_file_that_exists(self):
        if not record_media.MANIFEST.exists():  # pragma: no cover - always committed
            pytest.skip("no record manifest committed")
        manifest = json.loads(record_media.MANIFEST.read_text())
        assert manifest
        for key, entry in manifest.items():
            assert (record_media.SEED_DIR / entry["file"]).exists(), key
            assert key.split("|")[0] in record_media.SPEC_BY_LABEL, key

    def test_a_seeded_row_can_be_reseeded_without_changing(self):
        """`seed` runs on every deploy; the second run must be a no-op."""
        cms.Testimonial.objects.get_or_create(
            scope="landing", name="QA Reviewer", defaults={"quote": "Fine."}
        )
        record_media.attach_seed_record_images()
        assert record_media.attach_seed_record_images()[0] == 0


@pytest.mark.django_db
class TestSeedCommand:
    def test_the_domain_fills_rows_and_reports_what_is_left(self, capsys):
        from django.core.management import call_command

        CaseCard.objects.get_or_create(
            scope="landing", title="QA seeded card", defaults={"excerpt": "…"}
        )
        call_command("seed", "--domain", "record_media")

        out = capsys.readouterr().out
        assert "record media:" in out
        assert "still empty" in out
