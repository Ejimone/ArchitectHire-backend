"""Stage 1 of the Studio overhaul: empty slots, the slot editor, upload validation,
validation at stage time, generic append positions, page-tree records, pagination."""

import io

import pytest
from django.contrib.admin.sites import site as admin_site
from django.core.management import call_command
from PIL import Image

from apps.cms.models import (
    FAQ,
    CopyBlock,
    FooterColumn,
    FooterLink,
    MediaAsset,
    NavGroup,
    NavItem,
    PageSEO,
    Persona,
    SeedRun,
)
from apps.studio_api.drafts import DraftError, validate_payload
from apps.studio_api.models import ContentDraft, ContentRevision, StudioSession
from apps.studio_api.views import build_schema

MEDIA = "/api/v1/studio/media/"
LANDING = "/api/v1/studio/pages/landing/"
PAGES = "/api/v1/studio/pages/"


def png_bytes(size=(4, 4)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------- empty slots ---


@pytest.mark.django_db
class TestEmptySlots:
    def test_the_inventory_travels_in_edit_slots_including_empty_ones(self, studio_client):
        asset, _ = MediaAsset.objects.get_or_create(slot_key="landing:hero-arch")
        MediaAsset.objects.filter(pk=asset.pk).update(image="")
        body = studio_client.get(LANDING).json()
        slots = {entry["slot_key"]: entry for entry in body["_edit"]["slots"]}
        # `landing:hero-arch` is a static inventory slot with no image yet: it must be
        # addressable (has an id) and marked unfilled.
        assert slots["landing:hero-arch"]["filled"] is False
        assert slots["landing:hero-arch"]["id"] is not None
        assert slots["landing:hero-arch"]["notes"]
        assert "landing:hero-arch" not in body["media"]  # the public shape is untouched
        assert body["_edit"]["mode"] == "draft"

    def test_a_slot_the_inventory_does_not_know_is_still_listed(self, studio_client):
        MediaAsset.objects.create(slot_key="landing:ad-hoc-slot", notes="hand-made")
        body = studio_client.get(LANDING).json()
        slots = {entry["slot_key"]: entry for entry in body["_edit"]["slots"]}
        assert slots["landing:ad-hoc-slot"]["notes"] == "hand-made"

    def test_slots_not_yet_in_the_table_have_no_id(self, studio_client):
        MediaAsset.objects.filter(slot_key="landing:hero-arch").delete()
        body = studio_client.get(LANDING).json()
        slots = {entry["slot_key"]: entry for entry in body["_edit"]["slots"]}
        assert slots["landing:hero-arch"]["id"] is None
        assert slots["landing:hero-arch"]["focal_x"] == 0.5


# ---------------------------------------------------------------- slot editor ---


@pytest.mark.django_db
class TestMediaSlotView:
    url = "/api/v1/studio/media/landing/"

    def test_alt_text_on_an_empty_slot_creates_the_row_and_stages_it(self, studio_client):
        MediaAsset.objects.filter(slot_key="landing:slot-alt").delete()
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-alt/", {"alt_text": "A house"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert response.json()["image"] is None
        asset = MediaAsset.objects.get(slot_key="landing:slot-alt")
        draft = ContentDraft.objects.get(model_label="cms.mediaasset", object_id=asset.pk)
        assert draft.payload == {"alt_text": "A house"}

    def test_upload_through_the_slot_editor_clears_the_stock_credit(
        self, studio_client, image_upload
    ):
        asset = MediaAsset.objects.create(slot_key="landing:slot-up", credit="Stock Co.")
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-up/?mode=live",
            {"image": image_upload},
            format="multipart",
        )
        assert response.status_code == 200, response.content
        asset.refresh_from_db()
        assert asset.image
        assert asset.credit == ""
        assert response.json()["name"] == asset.image.name

    def test_reusing_a_library_image_by_name_inherits_its_credit(self, studio_client, image_upload):
        source = MediaAsset.objects.create(slot_key="landing:slot-src", credit="Photographer")
        source.image.save("src.png", image_upload, save=True)
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-dst/?mode=live",
            {"image": source.image.name},
            format="json",
        )
        assert response.status_code == 200, response.content
        target = MediaAsset.objects.get(slot_key="landing:slot-dst")
        assert target.image.name == source.image.name
        assert target.credit == "Photographer"

    def test_reusing_a_name_that_is_not_in_storage_is_a_400(self, studio_client):
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-x/", {"image": "cms/slots/nope.webp"}, format="json"
        )
        assert response.status_code == 400

    def test_clearing_the_image(self, studio_client, image_upload):
        asset = MediaAsset.objects.create(slot_key="landing:slot-clear", credit="Stock")
        asset.image.save("c.png", image_upload, save=True)
        response = studio_client.put(
            "/api/v1/studio/media/landing:slot-clear/?mode=live", {"image": ""}, format="json"
        )
        assert response.status_code == 200
        asset.refresh_from_db()
        assert asset.image == ""
        assert asset.credit == ""
        assert response.json()["image"] is None

    def test_focal_point_is_clamped_and_validated(self, studio_client):
        MediaAsset.objects.create(slot_key="landing:slot-focal")
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-focal/?mode=live",
            {"focal_x": 1.7, "focal_y": -2},
            format="json",
        )
        assert response.status_code == 200
        asset = MediaAsset.objects.get(slot_key="landing:slot-focal")
        assert (asset.focal_x, asset.focal_y) == (1.0, 0.0)
        bad = studio_client.patch(
            "/api/v1/studio/media/landing:slot-focal/", {"focal_x": "left"}, format="json"
        )
        assert bad.status_code == 400

    def test_notes_and_credit_are_editable(self, studio_client):
        MediaAsset.objects.create(slot_key="landing:slot-notes")
        response = studio_client.patch(
            "/api/v1/studio/media/landing:slot-notes/?mode=live",
            {"notes": "Hero", "credit": "Us"},
            format="json",
        )
        assert response.status_code == 200
        asset = MediaAsset.objects.get(slot_key="landing:slot-notes")
        assert (asset.notes, asset.credit) == ("Hero", "Us")

    def test_empty_body_and_bad_slot_key_are_400s(self, studio_client):
        assert (
            studio_client.patch("/api/v1/studio/media/landing:e/", {}, format="json").status_code
            == 400
        )
        assert (
            studio_client.patch(
                "/api/v1/studio/media/nope:e/", {"alt_text": "x"}, format="json"
            ).status_code
            == 400
        )


# ---------------------------------------------------------------- media list ---


@pytest.mark.django_db
class TestMediaList:
    def test_ordered_and_paginated_with_storage_names(self, studio_client, image_upload):
        for key in ("zz", "aa", "mm"):
            MediaAsset.objects.create(slot_key=f"landing:page-{key}", notes=f"note {key}")
        filled = MediaAsset.objects.get(slot_key="landing:page-mm")
        filled.image.save("mm.png", image_upload, save=True)

        body = studio_client.get(f"{MEDIA}?scope=landing&q=page-&page_size=2").json()
        assert body["count"] == 3
        assert body["pages"] == 2
        assert [s["slot_key"] for s in body["slots"]] == ["landing:page-aa", "landing:page-mm"]
        mm = body["slots"][1]
        assert mm["name"] == filled.image.name
        assert mm["credit"] == ""
        assert mm["focal_x"] == 0.5

        page2 = studio_client.get(f"{MEDIA}?scope=landing&q=page-&page_size=2&page=2").json()
        assert [s["slot_key"] for s in page2["slots"]] == ["landing:page-zz"]

    def test_search_matches_notes_and_alt_text(self, studio_client):
        MediaAsset.objects.create(slot_key="landing:q1", notes="Golden retriever portrait")
        MediaAsset.objects.create(slot_key="landing:q2", alt_text="A kitchen island")
        assert studio_client.get(f"{MEDIA}?q=retriever").json()["count"] == 1
        assert studio_client.get(f"{MEDIA}?q=island").json()["count"] == 1

    def test_bad_page_numbers_fall_back(self, studio_client):
        body = studio_client.get(f"{MEDIA}?page=zero&page_size=-4").json()
        assert body["page"] == 1
        assert body["page_size"] == 1


# ------------------------------------------------------------ upload validation ---


@pytest.mark.django_db
class TestUploadValidation:
    def test_a_non_image_is_refused(self, studio_client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        fake = SimpleUploadedFile("photo.jpg", b"%PDF-1.4 not an image", content_type="image/jpeg")
        response = studio_client.post(
            MEDIA, {"slot_key": "landing:bad", "image": fake}, format="multipart"
        )
        assert response.status_code == 400
        assert "not an image" in response.json()["detail"]

    def test_an_svg_is_refused_even_though_pillow_might_not_open_it(self, studio_client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        svg = SimpleUploadedFile("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        response = studio_client.post(
            "/api/v1/studio/uploads/",
            {"model_label": "cms.step", "field": "image", "file": svg},
            format="multipart",
        )
        assert response.status_code == 400

    def test_an_oversized_file_is_refused(self, studio_client, settings):
        from django.core.files.uploadedfile import SimpleUploadedFile

        settings.STUDIO_MAX_UPLOAD_BYTES = 10
        big = SimpleUploadedFile("big.png", png_bytes(), content_type="image/png")
        response = studio_client.post(
            MEDIA, {"slot_key": "landing:big", "image": big}, format="multipart"
        )
        assert response.status_code == 400
        assert "limit is 0 MB" in response.json()["detail"]

    def test_a_format_pillow_reads_but_the_site_does_not_serve_is_refused(self, studio_client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        buffer = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buffer, format="BMP")
        bmp = SimpleUploadedFile("scan.bmp", buffer.getvalue(), content_type="image/bmp")
        response = studio_client.post(
            MEDIA, {"slot_key": "landing:bmp", "image": bmp}, format="multipart"
        )
        assert response.status_code == 400
        assert "BMP is not supported" in response.json()["detail"]


# ------------------------------------------------------------- SEO og_image ---


@pytest.mark.django_db
def test_seo_accepts_og_image(studio_client, image_upload):
    upload = studio_client.post(
        "/api/v1/studio/uploads/",
        {"model_label": "cms.pageseo", "field": "og_image", "file": image_upload},
        format="multipart",
    )
    assert upload.status_code == 200, upload.content
    name = upload.json()["name"]
    response = studio_client.put(
        "/api/v1/studio/seo/landing/?mode=live",
        {"title": "Home", "og_image": name},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert PageSEO.objects.get(page_key="landing").og_image.name == name


# ------------------------------------------------------- validation at stage ---


@pytest.mark.django_db
class TestValidation:
    def test_a_missing_foreign_key_is_a_400_at_stage_time(self, studio_client):
        response = studio_client.post(
            "/api/v1/studio/rows/cms.navitem/",
            {"group": 999999, "label": "Ghost", "href": "/x"},
            format="json",
        )
        assert response.status_code == 400
        body = response.json()
        assert "group" in body["errors"]

    def test_a_blank_required_field_is_a_400(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Q?", answer="A")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/", {"question": ""}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["errors"]["question"]

    def test_a_bad_choice_is_a_400(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Q?", answer="A")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/", {"status": "maybe"}, format="json"
        )
        assert response.status_code == 400

    def test_too_long_text_is_a_400_in_live_mode_too(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Q?", answer="A")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/?mode=live",
            {"question": "x" * 1000},
            format="json",
        )
        assert response.status_code == 400
        faq.refresh_from_db()
        assert faq.question == "Q?"

    def test_a_valid_payload_passes(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Q?", answer="A")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/", {"question": "Better?"}, format="json"
        )
        assert response.status_code == 200

    def test_a_null_optional_relation_is_fine_and_a_null_required_one_is_not(self, db):
        group = NavGroup.objects.create(menu="services", heading="G")
        validate_payload(NavItem, {"group": group.pk, "label": "ok", "href": "/"})
        with pytest.raises(DraftError) as excinfo:
            validate_payload(NavItem, {"group": None, "label": "ok", "href": "/"})
        assert "group" in excinfo.value.errors

    def test_payload_without_model_fields_is_ignored(self, db):
        validate_payload(FAQ, {"not_a_field": 1})

    def test_publish_explains_a_database_refusal_instead_of_500ing(self, studio_client):
        # Two drafts creating the same copy key: the second violates the unique key at
        # publish time — something stage-time validation cannot see, because the first
        # row does not exist yet either.
        for _ in range(2):
            ContentDraft.objects.create(
                model_label="cms.copyblock",
                op=ContentDraft.Op.CREATE,
                scope="landing",
                payload={"scope": "landing", "key": "dup-key", "text": "x", "href": ""},
            )
        response = studio_client.post(
            "/api/v1/studio/publish/", {"scope": "landing"}, format="json"
        )
        assert response.status_code == 400
        assert "Could not publish" in response.json()["detail"]
        # Rolled back: neither the row nor a revision exists, and the drafts remain.
        assert not CopyBlock.objects.filter(scope="landing", key="dup-key").exists()
        assert not ContentRevision.objects.filter(scope="landing").exists()
        assert ContentDraft.objects.filter(scope="landing").count() == 2


# ------------------------------------------------------------ append position ---


@pytest.mark.django_db
class TestAppendPosition:
    def test_a_new_nav_item_lands_after_its_siblings(self, studio_client):
        group = NavGroup.objects.create(menu="services", heading="Services")
        NavItem.objects.create(group=group, label="A", href="/a", sort_order=0)
        NavItem.objects.create(group=group, label="B", href="/b", sort_order=1)
        other = NavGroup.objects.create(menu="projects", heading="Other")
        NavItem.objects.create(group=other, label="Z", href="/z", sort_order=9)

        studio_client.post(
            "/api/v1/studio/rows/cms.navitem/",
            {"group": group.pk, "label": "C", "href": "/c"},
            format="json",
        )
        draft = ContentDraft.objects.get(model_label="cms.navitem")
        assert draft.payload["sort_order"] == 2

        # A second pending item in the same group counts the first.
        studio_client.post(
            "/api/v1/studio/rows/cms.navitem/",
            {"group": group.pk, "label": "D", "href": "/d"},
            format="json",
        )
        latest = ContentDraft.objects.filter(model_label="cms.navitem").order_by("-pk").first()
        assert latest.payload["sort_order"] == 3

    def test_a_new_footer_link_in_live_mode_lands_last(self, studio_client):
        column = FooterColumn.objects.create(heading="Company")
        FooterLink.objects.create(column=column, label="About", href="/about", sort_order=4)
        response = studio_client.post(
            "/api/v1/studio/rows/cms.footerlink/?mode=live",
            {"column": column.pk, "label": "Careers", "href": "/careers"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert FooterLink.objects.get(column=column, label="Careers").sort_order == 5

    def test_a_flat_orderable_model_counts_all_rows(self, studio_client):
        from django.db.models import Max

        FooterColumn.objects.create(heading="One (probe)", sort_order=3)
        top = FooterColumn.objects.aggregate(Max("sort_order"))["sort_order__max"]
        response = studio_client.post(
            "/api/v1/studio/rows/cms.footercolumn/?mode=live",
            {"heading": "Two (probe)"},
            format="json",
        )
        assert response.status_code == 200
        assert FooterColumn.objects.get(heading="Two (probe)").sort_order == top + 1


# ------------------------------------------------------------------ page tree ---


@pytest.mark.django_db
class TestPageTree:
    def test_services_landing_routes_to_its_own_page(self, studio_client):
        body = studio_client.get(PAGES).json()
        pages = {p["key"]: p for s in body["sections"] for p in s["pages"]}
        assert pages["services-landing"]["route"] == "/services-landing"
        assert pages["services"]["route"] == "/services"

    def test_a_service_is_a_record_without_a_route(self, studio_client):
        from apps.catalog.models import Service, ServiceCategory

        category = ServiceCategory.objects.create(slug="cat", name="Cat")
        service = Service.objects.create(category=category, slug="probe-svc", name="Probe")
        body = studio_client.get(PAGES).json()
        pages = {p["key"]: p for s in body["sections"] for p in s["pages"]}
        ref = pages["service:probe-svc"]
        assert ref["route"] is None
        assert ref["editable"] is True
        assert ref["record"] == {"model": "catalog.service", "id": service.pk}
        assert pages["landing"]["record"] is None


# ------------------------------------------------------------------- schema ---


@pytest.mark.django_db
def test_schema_is_versioned_and_cached(studio_client):
    first = studio_client.get("/api/v1/studio/schema/").json()
    assert len(first["version"]) == 12
    assert build_schema() is build_schema()
    assert "og_image" in {f["name"] for f in first["models"]["cms.pageseo"]["fields"]}


# ------------------------------------------------------------- pagination ---


@pytest.mark.django_db
def test_queue_and_revisions_paginate(studio_client):
    for i in range(3):
        CopyBlock.objects.create(scope="landing", key=f"pg-{i}", text="x")
    for row in CopyBlock.objects.filter(key__startswith="pg-"):
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "y"}, format="json"
        )
    queue = studio_client.get("/api/v1/studio/queue/?page_size=2").json()
    assert queue["total"] == 3
    assert sum(len(s["changes"]) for s in queue["scopes"]) == 2
    studio_client.post("/api/v1/studio/publish/", {}, format="json")
    for row in CopyBlock.objects.filter(key__startswith="pg-"):
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/?mode=live", {"text": "z"}, format="json"
        )
    revisions = studio_client.get("/api/v1/studio/revisions/?page_size=2&page=2").json()
    assert revisions["count"] == 4
    assert len(revisions["revisions"]) == 2


# ---------------------------------------------------------------------- admin ---


@pytest.mark.django_db
class TestAdmin:
    def test_studio_tables_are_registered(self):
        registered = {model._meta.label_lower for model in admin_site._registry}
        assert {
            "studio_api.contentdraft",
            "studio_api.contentrevision",
            "studio_api.studiosession",
        } <= registered
        assert "cms.inspirationlike" in registered

    def test_revert_and_revoke_actions(self, staff_user, rf):
        from apps.studio_api.admin import ContentRevisionAdmin, StudioSessionAdmin

        row = CopyBlock.objects.create(scope="landing", key="adm", text="before")
        from apps.studio_api import drafts as engine

        _change, revision = engine.apply_now(
            model_label="cms.copyblock",
            op=ContentDraft.Op.UPDATE,
            object_id=row.pk,
            payload={"text": "after"},
            user=staff_user,
        )
        from django.contrib.messages.storage.cookie import CookieStorage

        request = rf.post("/admin/")
        request.user = staff_user
        request._messages = CookieStorage(request)
        ContentRevisionAdmin(ContentRevision, admin_site).revert_selected(
            request, ContentRevision.objects.filter(pk=revision.pk)
        )
        row.refresh_from_db()
        assert row.text == "before"
        assert not ContentRevisionAdmin(ContentRevision, admin_site).has_add_permission(request)

        session, _token = StudioSession.issue(staff_user)
        admin = StudioSessionAdmin(StudioSession, admin_site)
        assert admin.is_active(session) is True
        admin.revoke_selected(request, StudioSession.objects.filter(pk=session.pk))
        session.refresh_from_db()
        assert admin.is_active(session) is False
        assert not admin.has_add_permission(request)


# ------------------------------------------------------------ seed is a floor ---


@pytest.mark.django_db
class TestSeedFloor:
    def test_a_seeded_domain_is_skipped_unless_overwrite(self, capsys):
        SeedRun.objects.get_or_create(domain="content")
        CopyBlock.objects.update_or_create(
            scope="landing", key="hero_h1", defaults={"text": "Owner's headline"}
        )
        call_command("seed", "--domain", "content")
        assert CopyBlock.objects.get(scope="landing", key="hero_h1").text == "Owner's headline"
        assert "already seeded" in capsys.readouterr().out

        call_command("seed", "--domain", "content", "--overwrite")
        assert CopyBlock.objects.get(scope="landing", key="hero_h1").text != "Owner's headline"

    def test_a_first_run_records_the_marker(self):
        SeedRun.objects.filter(domain="payments").delete()
        call_command("seed", "--domain", "payments")
        assert SeedRun.objects.filter(domain="payments").exists()

    def test_the_backfill_marks_an_already_seeded_database(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        migration = import_module("apps.cms.migrations.0012_seedrun")
        SeedRun.objects.all().delete()
        CopyBlock.objects.create(scope="landing", key="bf", text="x")
        migration.backfill(global_apps, None)
        assert SeedRun.objects.count() == len(migration.FLOOR_DOMAINS)

        SeedRun.objects.all().delete()
        CopyBlock.objects.all().delete()
        migration.backfill(global_apps, None)
        assert SeedRun.objects.count() == 0


# ------------------------------------------------------ inspiration cover hint ---


@pytest.mark.django_db
def test_persona_image_hint_and_terms_repair_migration(api_client):
    from importlib import import_module

    from django.apps import apps as global_apps

    Persona.objects.get_or_create(
        scope="inspiration",
        group="collections",
        title="Kitchens that open up",
        defaults={"kicker": "1"},
    )
    CopyBlock.objects.update_or_create(
        scope="chrome", key="footer_terms", defaults={"text": "Terms", "href": "/privacy#terms"}
    )
    migration = import_module("apps.cms.migrations.0011_terms_links_and_collection_hints")
    migration.forwards(global_apps, None)
    assert CopyBlock.objects.get(scope="chrome", key="footer_terms").href == "/terms"
    hints_in_db = set(
        Persona.objects.filter(title="Kitchens that open up").values_list("image_hint", flat=True)
    )
    assert hints_in_db == {"Kitchen collection cover"}
    payload = api_client.get("/api/v1/content/pages/inspiration/").json()
    hints = [p["image_hint"] for p in payload["blocks"]["personas"]]
    assert "Kitchen collection cover" in hints


@pytest.mark.django_db
def test_media_asset_focal_point_is_served(api_client, image_upload):
    asset = MediaAsset.objects.create(slot_key="landing:focal-probe", focal_x=0.2, focal_y=0.9)
    asset.image.save("f.png", image_upload, save=True)
    payload = api_client.get("/api/v1/content/pages/landing/").json()
    entry = payload["media"]["landing:focal-probe"]
    assert (entry["focal_x"], entry["focal_y"]) == (0.2, 0.9)


@pytest.mark.django_db
def test_per_page_slot_inventory_matches_the_full_walk():
    from apps.catalog.models import ProjectType
    from apps.cms.models import CaseCard
    from apps.cms.slots import expected_media_slots
    from apps.jurisdictions.models import City, State

    state, _ = State.objects.get_or_create(
        code="ZZ", defaults={"name": "Zeta", "complexity_score": 1, "region": "West"}
    )
    City.objects.get_or_create(slug="probe-city", defaults={"name": "Probe City", "state": state})
    project, _ = ProjectType.objects.get_or_create(
        slug="probe-project",
        defaults={"name": "Probe project", "slot_id": "probe-card", "group": "residential"},
    )
    CaseCard.objects.get_or_create(
        scope="project-type:probe-project", group="gallery", title="G1", defaults={"sort_order": 0}
    )

    full = dict(expected_media_slots())
    for page_key in ("city:probe-city", "cities", "project-type:probe-project", "projects"):
        subset = dict(expected_media_slots(page_key))
        assert subset, page_key
        assert all(key.rpartition(":")[0] == page_key for key in subset), page_key
        assert subset == {k: v for k, v in full.items() if k.rpartition(":")[0] == page_key}
    assert str(SeedRun(domain="content")) == "content"


@pytest.mark.django_db
def test_live_delete_of_a_missing_row_is_a_400(studio_client):
    response = studio_client.delete("/api/v1/studio/rows/cms.faq/987654/?mode=live")
    assert response.status_code == 400
