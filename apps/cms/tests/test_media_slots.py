"""Image-slot inventory: auto-created rows, signal sync, key validation."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.catalog.models import ProjectType
from apps.cms.admin import MediaAssetAdmin
from apps.cms.models import CaseCard, HeroCarouselSlide, MediaAsset, Persona, Testimonial
from apps.cms.slots import STATIC_SLOTS, expected_media_slots, sync_media_slots
from apps.core.scopes import validate_slot_key
from apps.jurisdictions.models import City, State


@pytest.fixture()
def city(db):
    state = State.objects.create(code="QA", name="QA State", complexity_score=1, region="West")
    return City.objects.create(state=state, name="Slotville", slug="slotville")


class TestSlotKeyValidation:
    def test_scope_colon_slot_keys_are_valid(self):
        validate_slot_key("landing:hero-arch")
        validate_slot_key("city:oakland:work-1")
        validate_slot_key("project-type:adu:proj-hero2")

    @pytest.mark.parametrize("bad", ["no-colon", "not-a-page:hero", "landing:", "landing:UPPER"])
    def test_invalid_keys_are_rejected(self, bad):
        with pytest.raises(ValidationError, match="not a valid slot key"):
            validate_slot_key(bad)

    def test_admin_can_save_a_row_with_a_colon_key(self, db):
        asset = MediaAsset(slot_key="landing:qa-probe", notes="x")
        asset.full_clean()  # SlugField used to reject the colon here

    def test_every_static_slot_passes_validation(self):
        for key, _notes in STATIC_SLOTS:
            validate_slot_key(key)


@pytest.mark.django_db
class TestInventoryAndSync:
    def test_db_derived_slots_follow_content(self, city):
        Testimonial.objects.create(scope="city:slotville", name="A", quote="q")
        project = ProjectType.objects.create(
            group="residential", name="QA Cabin", slug="qa-cabin", slot_id="ps-qa"
        )
        CaseCard.objects.create(scope="project-type:qa-cabin", group="gallery", title="Shot")
        keys = dict(expected_media_slots())
        assert keys["cities:city-slotville"] == "Cities index — card photo for Slotville"
        assert "city:slotville:hero" in keys
        assert "city:slotville:work-1" in keys
        assert "projects:ps-qa" in keys
        assert "project-type:qa-cabin:proj-hero1" in keys
        assert "project-type:qa-cabin:p-g1" in keys
        project.slot_id = ""
        project.save()
        assert "projects:ps-qa" not in dict(expected_media_slots())

    def test_signals_create_and_prune_rows(self, city):
        assert MediaAsset.objects.filter(slot_key="city:slotville:hero").exists()
        t = Testimonial.objects.create(scope="city:slotville", name="A", quote="q")
        assert MediaAsset.objects.filter(slot_key="city:slotville:work-1").exists()
        t.delete()
        assert not MediaAsset.objects.filter(slot_key="city:slotville:work-1").exists()

    def test_rows_with_an_uploaded_image_survive_pruning(self, city):
        t = Testimonial.objects.create(scope="city:slotville", name="A", quote="q")
        MediaAsset.objects.filter(slot_key="city:slotville:work-1").update(image="cms/slots/x.jpg")
        t.delete()
        assert MediaAsset.objects.filter(slot_key="city:slotville:work-1").exists()

    def test_fixture_loads_skip_sync(self, city):
        from django.apps import apps as global_apps
        from django.db.models.signals import post_save

        before = MediaAsset.objects.count()
        post_save.send(sender=global_apps.get_model("jurisdictions.City"), instance=city, raw=True)
        assert MediaAsset.objects.count() == before

    def test_sync_is_idempotent(self, city):
        created, pruned = sync_media_slots()
        assert (created, pruned) == (0, 0)

    def test_service_gallery_slots_follow_their_rows(self, db):
        """The service-detail galleries render `media[f"{scope}:{prefix}{i+1}"]` per row.

        These were missing from the inventory entirely, so they never appeared in the
        media library — and because pruning is driven by the same inventory, anything
        that did create them got deleted again on the next sync.
        """
        # The studio suite runs with `transaction=True`, so rows from other tests can be
        # committed and still visible here — start from a known count for these scopes.
        HeroCarouselSlide.objects.filter(scope="cad-drafting").delete()
        CaseCard.objects.filter(scope="cad-drafting").delete()
        Persona.objects.filter(scope="3d-visualization").delete()

        HeroCarouselSlide.objects.create(scope="cad-drafting", caption="one")
        HeroCarouselSlide.objects.create(scope="cad-drafting", caption="two")
        CaseCard.objects.create(scope="cad-drafting", title="Specialist")
        Persona.objects.create(scope="3d-visualization", kicker="THE ARTIST", title="Viz lead")

        keys = dict(expected_media_slots())
        assert keys["cad-drafting:cad-g1"] == "CAD Drafting — work gallery tile 1"
        assert "cad-drafting:cad-g2" in keys
        assert "cad-drafting:cad-g3" not in keys  # only two slides exist
        assert "cad-drafting:cad-s1" in keys
        assert "3d-visualization:viz-s1" in keys

        # And the rows really are created, then pruned when the content goes away.
        assert MediaAsset.objects.filter(slot_key="cad-drafting:cad-g2").exists()
        HeroCarouselSlide.objects.filter(scope="cad-drafting", caption="two").delete()
        assert not MediaAsset.objects.filter(slot_key="cad-drafting:cad-g2").exists()


@pytest.mark.django_db
class TestSyncMediaSlotsCommand:
    def test_dry_run_reports_without_writing(self, city, capsys):
        MediaAsset.objects.filter(slot_key="landing:hero-arch").delete()
        MediaAsset.objects.create(slot_key="landing:qa-orphan", notes="gone")
        before = MediaAsset.objects.count()

        call_command("sync_media_slots", "--dry-run")

        assert MediaAsset.objects.count() == before  # nothing written
        out = capsys.readouterr().out
        assert "+ landing:hero-arch" in out
        assert "- landing:qa-orphan" in out
        assert "1 to create, 1 to prune" in out

    def test_apply_creates_and_prunes(self, city, capsys):
        MediaAsset.objects.filter(slot_key="landing:hero-arch").delete()
        MediaAsset.objects.create(slot_key="landing:qa-orphan", notes="gone")

        call_command("sync_media_slots")

        assert MediaAsset.objects.filter(slot_key="landing:hero-arch").exists()
        assert not MediaAsset.objects.filter(slot_key="landing:qa-orphan").exists()
        assert "1 new, 1 pruned" in capsys.readouterr().out

    def test_reports_how_many_slots_still_need_an_upload(self, city, capsys):
        MediaAsset.objects.filter(slot_key="landing:hero-arch").update(image="cms/slots/x.jpg")
        call_command("sync_media_slots")
        out = capsys.readouterr().out
        assert "1 filled" in out
        assert "awaiting an upload" in out

    def test_seed_media_reports_and_refreshes_notes(self, city, capsys):
        MediaAsset.objects.filter(slot_key="landing:hero-arch").update(notes="stale")
        call_command("seed", "--domain", "media")
        assert MediaAsset.objects.get(slot_key="landing:hero-arch").notes != "stale"
        out = capsys.readouterr().out
        assert "media:" in out


@pytest.mark.django_db
class TestAdmin:
    def test_slot_key_locked_for_staff_but_repairable_by_a_superuser(self):
        """Staff must not invent slot keys; superusers must be able to repair one.

        `sync_media_slots` only prunes rows with no image, so a *filled* row saved under
        a wrong key renders nowhere and cannot be cleaned up automatically. Locking the
        field for everyone left that row permanently stuck.
        """
        admin = MediaAssetAdmin(MediaAsset, None)
        asset = MediaAsset.objects.create(slot_key="landing:qa-readonly-probe", notes="x")
        staff = SimpleNamespace(is_superuser=False)
        owner = SimpleNamespace(is_superuser=True)

        assert admin.get_readonly_fields(SimpleNamespace(user=staff), asset) == ["slot_key"]
        assert admin.get_readonly_fields(SimpleNamespace(user=owner), asset) == []
        # Adding a row: nothing is locked, for either.
        assert admin.get_readonly_fields(SimpleNamespace(user=staff), None) == []
