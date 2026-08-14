"""Media, schema, and the edit endpoints' error paths."""

import datetime as dt
from decimal import Decimal

import pytest

from apps.cms.models import FAQ, CopyBlock, MediaAsset, Testimonial
from apps.cms.models_editorial import BlogPost
from apps.studio_api.fields import assign, editable_fields, field_schema, snapshot
from apps.studio_api.models import ContentDraft

MEDIA = "/api/v1/studio/media/"
SCHEMA = "/api/v1/studio/schema/"
LANDING = "/api/v1/studio/pages/landing/"


@pytest.mark.django_db
class TestMediaLibrary:
    def test_upload_fills_a_slot_as_a_draft(self, studio_client, image_upload, api_client):
        response = studio_client.post(
            MEDIA,
            {"slot_key": "landing:upload-probe", "image": image_upload, "alt_text": "A house"},
            format="multipart",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["slot_key"] == "landing:upload-probe"
        assert body["image"].startswith("http")

        # Staged, so the live row is still empty.
        assert MediaAsset.objects.get(slot_key="landing:upload-probe").image == ""
        canvas = studio_client.get(LANDING).json()["media"]["landing:upload-probe"]
        assert canvas["alt_text"] == "A house"

    def test_upload_creates_a_slot_the_inventory_has_not_seen(self, studio_client, image_upload):
        assert not MediaAsset.objects.filter(slot_key="landing:brand-new-slot").exists()
        studio_client.post(
            MEDIA,
            {"slot_key": "landing:brand-new-slot", "image": image_upload},
            format="multipart",
        )
        assert MediaAsset.objects.filter(slot_key="landing:brand-new-slot").exists()

    def test_upload_without_a_file_is_a_400(self, studio_client):
        response = studio_client.post(MEDIA, {"slot_key": "landing:x"}, format="multipart")
        assert response.status_code == 400

    def test_slot_key_must_stay_inside_a_real_scope(self, studio_client, image_upload):
        response = studio_client.post(
            MEDIA,
            {"slot_key": "not-a-page:hero", "image": image_upload},
            format="multipart",
        )
        assert response.status_code == 400

    def test_library_filters_by_scope_search_and_state(self, studio_client, image_upload):
        filled = MediaAsset.objects.create(slot_key="landing:lib-filled")
        filled.image.save("filled.png", image_upload, save=True)
        MediaAsset.objects.create(slot_key="landing:lib-empty")

        scoped = studio_client.get(f"{MEDIA}?scope=landing").json()
        assert {"landing:lib-filled", "landing:lib-empty"} <= {
            s["slot_key"] for s in scoped["slots"]
        }

        searched = studio_client.get(f"{MEDIA}?q=lib-filled").json()
        assert [s["slot_key"] for s in searched["slots"]] == ["landing:lib-filled"]

        only_filled = studio_client.get(f"{MEDIA}?q=lib-&state=filled").json()
        assert [s["slot_key"] for s in only_filled["slots"]] == ["landing:lib-filled"]
        assert only_filled["slots"][0]["image"].startswith("http")

        only_empty = studio_client.get(f"{MEDIA}?q=lib-&state=empty").json()
        assert [s["slot_key"] for s in only_empty["slots"]] == ["landing:lib-empty"]
        assert only_empty["slots"][0]["image"] is None

    def test_sync_rebuilds_the_inventory(self, studio_client):
        body = studio_client.post("/api/v1/studio/media/sync/").json()
        assert "created" in body and "pruned" in body


@pytest.mark.django_db
class TestSchema:
    def test_every_editable_model_describes_its_fields(self, studio_client):
        models = studio_client.get(SCHEMA).json()["models"]
        assert models["cms.faq"]["collection"] == "faqs"
        names = {f["name"] for f in models["cms.faq"]["fields"]}
        assert {"question", "answer", "scope", "group", "sort_order"} <= names

        # Chrome models are editable but belong to no block collection.
        assert models["cms.copyblock"]["collection"] is None

    def test_bookkeeping_fields_are_marked_system(self, studio_client):
        fields = {
            f["name"]: f for f in studio_client.get(SCHEMA).json()["models"]["cms.faq"]["fields"]
        }
        assert fields["scope"]["system"] is True
        assert fields["question"]["system"] is False
        assert fields["answer"]["type"] == "textarea"

    def test_widgets_cover_the_shapes_the_inspector_renders(self, studio_client):
        models = studio_client.get(SCHEMA).json()["models"]
        testimonial = {f["name"]: f for f in models["cms.testimonial"]["fields"]}
        assert testimonial["photo"]["type"] == "image"
        assert testimonial["audience"]["type"] == "choice"
        assert {c["value"] for c in testimonial["audience"]["choices"]} == {
            "client",
            "architect",
            "expert",
        }
        settings_fields = {f["name"]: f for f in models["cms.sitesettings"]["fields"]}
        assert settings_fields["promo_banner_enabled"]["type"] == "boolean"
        assert settings_fields["hero_video_url"]["type"] == "url"
        assert settings_fields["contact_email_clients"]["type"] == "email"
        teaser = {f["name"]: f for f in models["cms.estimateteaseroption"]["fields"]}
        assert teaser["bar_pct"]["type"] == "number"
        nav = {f["name"]: f for f in models["cms.navitem"]["fields"]}
        assert nav["group"]["type"] == "relation"
        assert nav["group"]["relation"] == "cms.navgroup"


@pytest.mark.django_db
class TestFieldHelpers:
    def test_snapshot_and_assign_round_trip(self, image_upload):
        row = Testimonial(scope="landing", quote="Q", name="N", audience="client")
        row.photo.save("t.png", image_upload, save=False)
        data = snapshot(row)
        assert data["photo"] == row.photo.name
        assert data["quote"] == "Q"

        restored = Testimonial()
        written = assign(restored, {**data, "not_a_field": "ignored"})
        assert "not_a_field" not in written
        assert restored.quote == "Q"
        assert restored.photo.name == data["photo"]

    def test_datetime_and_relation_fields_survive_json(self, db):
        post = BlogPost(slug="fields-probe", title="T")
        post.published_at = dt.datetime(2026, 3, 4, 5, 6, tzinfo=dt.UTC)
        data = snapshot(post)
        assert data["published_at"] == "2026-03-04T05:06:00+00:00"
        assert data["author"] is None

        restored = BlogPost()
        assign(restored, data)
        assert restored.published_at == post.published_at
        assert restored.author_id is None

    def test_decimals_are_stringified_rather_than_rounded(self):
        from apps.catalog.models import RenderDeliverable

        row = RenderDeliverable(name="Still", unit="each", conceptual=Decimal("120.50"))
        assert snapshot(row)["conceptual"] == "120.50"

    def test_dates_round_trip(self):
        from apps.cms.models_editorial import PolicyPage

        row = PolicyPage(slug="privacy", title="Privacy", effective_date=dt.date(2026, 1, 2))
        data = snapshot(row)
        assert data["effective_date"] == "2026-01-02"
        restored = PolicyPage()
        assign(restored, data)
        assert restored.effective_date == dt.date(2026, 1, 2)

    def test_bookkeeping_columns_are_never_editable(self):
        names = {f.name for f in editable_fields(FAQ)}
        assert "id" not in names and "created_at" not in names and "updated_at" not in names

    def test_schema_reports_required_and_max_length(self):
        fields = {f["name"]: f for f in field_schema(FAQ)}
        assert fields["question"]["required"] is True
        assert fields["question"]["max_length"] == 255
        assert fields["answer"]["required"] is True  # TextField, but not blank=True
        assert fields["group"]["required"] is False  # blank=True
        assert fields["sort_order"]["required"] is False  # has a default


@pytest.mark.django_db
class TestEditErrorPaths:
    def test_copy_upsert_creates_a_row_that_did_not_exist(self, studio_client):
        CopyBlock.objects.filter(scope="landing", key="upsert-probe").delete()
        response = studio_client.put(
            "/api/v1/studio/copy/landing/upsert-probe/?mode=live",
            {"text": "Fresh", "href": "/x"},
            format="json",
        )
        assert response.status_code == 200
        assert CopyBlock.objects.get(scope="landing", key="upsert-probe").text == "Fresh"

    def test_copy_upsert_updates_an_existing_row(self, studio_client):
        CopyBlock.objects.update_or_create(
            scope="landing", key="upsert-existing", defaults={"text": "Old"}
        )
        studio_client.put(
            "/api/v1/studio/copy/landing/upsert-existing/?mode=live",
            {"text": "New"},
            format="json",
        )
        assert CopyBlock.objects.get(scope="landing", key="upsert-existing").text == "New"

    def test_copy_on_an_unknown_page_404s(self, studio_client):
        assert (
            studio_client.put(
                "/api/v1/studio/copy/not-a-page/k/", {"text": "x"}, format="json"
            ).status_code
            == 404
        )

    def test_seo_on_an_unknown_page_404s(self, studio_client):
        assert (
            studio_client.put(
                "/api/v1/studio/seo/not-a-page/", {"title": "x"}, format="json"
            ).status_code
            == 404
        )

    def test_a_model_outside_the_allowlist_is_refused(self, studio_client):
        for url, method in [
            ("/api/v1/studio/rows/accounts.user/", "post"),
            ("/api/v1/studio/rows/accounts.user/1/", "patch"),
            ("/api/v1/studio/rows/accounts.user/1/", "delete"),
            ("/api/v1/studio/rows/accounts.user/reorder/", "post"),
        ]:
            response = getattr(studio_client, method)(url, {}, format="json")
            assert response.status_code == 400, url

    def test_reorder_needs_a_non_empty_list(self, studio_client):
        assert (
            studio_client.post(
                "/api/v1/studio/rows/cms.faq/reorder/", {"ids": []}, format="json"
            ).status_code
            == 400
        )

    def test_a_pending_create_can_be_edited_and_discarded(self, studio_client):
        canvas_id = studio_client.post(
            "/api/v1/studio/rows/cms.faq/",
            {"scope": "landing", "question": "Draft edit?", "answer": "A"},
            format="json",
        ).json()["object_id"]

        studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{canvas_id}/", {"answer": "B"}, format="json"
        )
        draft = ContentDraft.objects.get(pk=-canvas_id)
        assert draft.payload["answer"] == "B"

        response = studio_client.delete(f"/api/v1/studio/rows/cms.faq/{canvas_id}/")
        assert response.json()["op"] == "discarded"
        assert not ContentDraft.objects.filter(pk=-canvas_id).exists()

    def test_editing_a_pending_row_that_is_gone_is_a_400(self, studio_client):
        response = studio_client.patch(
            "/api/v1/studio/rows/cms.faq/-999999/", {"answer": "x"}, format="json"
        )
        assert response.status_code == 400

    def test_resort_tolerates_a_collection_emptied_by_drafts(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Only one?", answer="A")
        studio_client.delete(f"/api/v1/studio/rows/cms.faq/{faq.pk}/")
        body = studio_client.get(LANDING).json()
        assert faq.pk not in [f["id"] for f in body["blocks"].get("faqs", [])]


@pytest.mark.django_db
class TestRowImageUpload:
    """Images that belong to a block row rather than a named media slot — a step
    illustration, a testimonial portrait — go through `/uploads/` and are then written
    onto the row like any other field value."""

    URL = "/api/v1/studio/uploads/"

    def test_upload_returns_a_storage_name_the_row_can_point_at(self, studio_client, image_upload):
        response = studio_client.post(
            self.URL,
            {"model_label": "cms.testimonial", "field": "photo", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"].startswith("cms/testimonials/")
        assert body["url"].startswith("http")

        # The name is a plain field value from here on.
        row = Testimonial.objects.create(scope="landing", quote="Q", name="N")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.testimonial/{row.pk}/?mode=live",
            {"photo": body["name"]},
            format="json",
        )
        row.refresh_from_db()
        assert row.photo.name == body["name"]

    def test_a_file_is_required(self, studio_client):
        response = studio_client.post(
            self.URL, {"model_label": "cms.testimonial", "field": "photo"}, format="multipart"
        )
        assert response.status_code == 400

    def test_an_unknown_field_is_refused(self, studio_client, image_upload):
        response = studio_client.post(
            self.URL,
            {"model_label": "cms.testimonial", "field": "nope", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 400

    def test_a_field_that_holds_no_file_is_refused(self, studio_client, image_upload):
        response = studio_client.post(
            self.URL,
            {"model_label": "cms.testimonial", "field": "quote", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 400

    def test_a_model_outside_the_allowlist_is_refused(self, studio_client, image_upload):
        response = studio_client.post(
            self.URL,
            {"model_label": "accounts.user", "field": "avatar_url", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 400


@pytest.mark.django_db
def test_staging_a_chrome_row_skips_the_append_position(studio_client):
    """`_append_position` only applies to scoped blocks. A copy row has no `sort_order`,
    so staging one must not try to look up its siblings."""
    CopyBlock.objects.filter(scope="landing", key="draft-create-probe").delete()
    response = studio_client.put(
        "/api/v1/studio/copy/landing/draft-create-probe/",
        {"text": "Staged", "href": ""},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["op"] == "create"
    assert not CopyBlock.objects.filter(scope="landing", key="draft-create-probe").exists()
    assert studio_client.get(LANDING).json()["copy"]["draft-create-probe"]["text"] == "Staged"
