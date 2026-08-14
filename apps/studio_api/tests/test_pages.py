"""The canvas payload.

The load-bearing assertion in here is `test_live_mode_matches_the_public_endpoint`: the
Studio renders the site's own components against this payload, so the moment its shape
drifts from `/api/v1/content/pages/<key>/` the preview stops being a preview.
"""

import pytest

from apps.cms.models import FAQ, CopyBlock, MediaAsset, PageSEO, Persona
from apps.studio_api.models import ContentDraft

PAGES = "/api/v1/studio/pages/"
LANDING = "/api/v1/studio/pages/landing/"
PUBLIC_LANDING = "/api/v1/content/pages/landing/"


@pytest.mark.django_db
class TestPageList:
    def test_tree_is_grouped_into_sections(self, studio_client):
        body = studio_client.get(PAGES).json()
        sections = {s["section"]: s["pages"] for s in body["sections"]}
        assert "Marketing" in sections
        keys = {p["key"] for p in sections["Marketing"]}
        assert {"landing", "about", "services"} <= keys

    def test_pages_without_a_public_route_are_flagged_uneditable(self, studio_client):
        body = studio_client.get(PAGES).json()
        pages = {p["key"]: p for s in body["sections"] for p in s["pages"]}
        assert pages["landing"]["editable"] is True
        assert pages["landing"]["route"] == "/"
        # Signed-in surfaces have no previewable URL.
        assert pages["account"]["editable"] is False

    def test_pending_counts_surface_per_page(self, studio_client, staff_user):
        row = CopyBlock.objects.create(scope="landing", key="tree-count-probe", text="x")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "y"}, format="json"
        )
        body = studio_client.get(PAGES).json()
        pages = {p["key"]: p for s in body["sections"] for p in s["pages"]}
        assert pages["landing"]["pending"] >= 1
        assert body["pending_total"] >= 1


@pytest.mark.django_db
class TestPageDetail:
    def test_unknown_page_404(self, studio_client):
        assert studio_client.get("/api/v1/studio/pages/not-a-page/").status_code == 404

    def test_live_mode_matches_the_public_endpoint(self, studio_client, api_client):
        FAQ.objects.create(scope="landing", question="Shape probe?", answer="A")
        CopyBlock.objects.create(scope="landing", key="shape-probe", text="Hello")

        studio = studio_client.get(f"{LANDING}?mode=live").json()
        public = api_client.get(PUBLIC_LANDING).json()

        # The studio adds three keys of its own and is otherwise byte-identical.
        extra = {"pending", "_edit", "route"}
        assert set(studio) - set(public) == extra
        for key in public:
            assert studio[key] == public[key], key

    def test_draft_mode_includes_unpublished_blocks(self, studio_client, api_client):
        # A published sibling, so the collection exists in both payloads: `compose_page`
        # omits a block key entirely when it has no rows.
        FAQ.objects.create(scope="landing", question="Published sibling?", answer="A")
        FAQ.objects.create(
            scope="landing", question="Unpublished probe?", answer="A", status="draft"
        )
        draft_questions = [
            f["question"] for f in studio_client.get(LANDING).json()["blocks"]["faqs"]
        ]
        live_questions = [
            f["question"] for f in api_client.get(PUBLIC_LANDING).json()["blocks"]["faqs"]
        ]
        assert "Unpublished probe?" in draft_questions
        assert "Unpublished probe?" not in live_questions

    def test_edit_map_addresses_copy_media_and_seo(self, studio_client, image_upload):
        copy_row = CopyBlock.objects.create(scope="landing", key="edit-map-probe", text="x")
        seo, _ = PageSEO.objects.update_or_create(page_key="landing", defaults={"title": "Landing"})
        asset = MediaAsset.objects.create(slot_key="landing:edit-map-probe")
        asset.image.save("probe.png", image_upload, save=True)
        FAQ.objects.create(scope="landing", question="Edit map probe?", answer="A")

        edit = studio_client.get(LANDING).json()["_edit"]
        assert edit["scope"] == "landing"
        assert edit["copy"]["edit-map-probe"] == {"model": "cms.copyblock", "id": copy_row.pk}
        assert edit["media"]["landing:edit-map-probe"] == {
            "model": "cms.mediaasset",
            "id": asset.pk,
        }
        assert edit["seo"] == {"model": "cms.pageseo", "id": seo.pk}
        assert edit["blocks"]["faqs"] == {"model": "cms.faq"}

    def test_route_is_returned_for_the_preview_link(self, studio_client):
        assert studio_client.get(LANDING).json()["route"] == "/"


@pytest.mark.django_db
class TestDraftOverlay:
    """A staged edit has to preview through the real serializer, not by patching JSON."""

    def test_copy_edit_shows_on_the_canvas_but_not_the_site(self, studio_client, api_client):
        row = CopyBlock.objects.create(scope="landing", key="overlay-copy", text="Before")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/",
            {"text": "After"},
            format="json",
        )
        assert studio_client.get(LANDING).json()["copy"]["overlay-copy"]["text"] == "After"
        assert api_client.get(PUBLIC_LANDING).json()["copy"]["overlay-copy"]["text"] == "Before"

    def test_pending_map_names_the_edited_row(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="overlay-pending", text="x")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "y"}, format="json"
        )
        pending = studio_client.get(LANDING).json()["pending"]
        assert pending[f"cms.copyblock:{row.pk}"] == "update"

    def test_pending_create_appears_with_a_negative_id(self, studio_client):
        response = studio_client.post(
            "/api/v1/studio/rows/cms.faq/",
            {"scope": "landing", "question": "Pending create?", "answer": "Yes"},
            format="json",
        )
        canvas_id = response.json()["object_id"]
        assert canvas_id < 0

        faqs = studio_client.get(LANDING).json()["blocks"]["faqs"]
        row = next(f for f in faqs if f["id"] == canvas_id)
        assert row["question"] == "Pending create?"
        assert not FAQ.objects.filter(question="Pending create?").exists()

    def test_staged_delete_disappears_from_the_canvas(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Doomed?", answer="A")
        studio_client.delete(f"/api/v1/studio/rows/cms.faq/{faq.pk}/")
        ids = [f["id"] for f in studio_client.get(LANDING).json()["blocks"]["faqs"]]
        assert faq.pk not in ids
        assert FAQ.objects.filter(pk=faq.pk).exists()

    def test_derived_serializer_fields_are_previewed_correctly(self, studio_client):
        """`Persona.points` is newline text the site reads as `points_list` — an overlay
        that patched raw field values would preview a string where a list belongs."""
        persona = Persona.objects.create(scope="landing", kicker="K", title="T", points="one\ntwo")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.persona/{persona.pk}/",
            {"points": "alpha\nbeta\ngamma"},
            format="json",
        )
        rows = studio_client.get(LANDING).json()["blocks"]["personas"]
        row = next(r for r in rows if r["id"] == persona.pk)
        assert row["points"] == ["alpha", "beta", "gamma"]

    def test_reorder_reflows_the_collection(self, studio_client):
        first = FAQ.objects.create(scope="landing", question="RO-1?", answer="A", sort_order=9001)
        second = FAQ.objects.create(scope="landing", question="RO-2?", answer="B", sort_order=9002)
        studio_client.post(
            "/api/v1/studio/rows/cms.faq/reorder/",
            {"ids": [second.pk, first.pk]},
            format="json",
        )
        faqs = studio_client.get(LANDING).json()["blocks"]["faqs"]
        ordered = [f["id"] for f in faqs if f["id"] in (first.pk, second.pk)]
        assert ordered == [second.pk, first.pk]

    def test_stale_update_draft_is_skipped(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Vanishing?", answer="A")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/", {"answer": "B"}, format="json"
        )
        FAQ.objects.filter(pk=faq.pk).delete()  # removed in Django admin behind our back
        body = studio_client.get(LANDING).json()
        assert faq.pk not in [f["id"] for f in body["blocks"].get("faqs", [])]

    def test_media_draft_fills_and_clears_a_slot(self, studio_client, image_upload):
        asset = MediaAsset.objects.create(slot_key="landing:overlay-media")
        assert "landing:overlay-media" not in studio_client.get(LANDING).json()["media"]

        studio_client.post(
            "/api/v1/studio/media/",
            {"slot_key": "landing:overlay-media", "image": image_upload},
            format="multipart",
        )
        assert "landing:overlay-media" in studio_client.get(LANDING).json()["media"]

        ContentDraft.objects.filter(model_label="cms.mediaasset", object_id=asset.pk).update(
            payload={"image": ""}
        )
        assert "landing:overlay-media" not in studio_client.get(LANDING).json()["media"]

    def test_staged_media_delete_removes_the_slot(self, studio_client, image_upload):
        asset = MediaAsset.objects.create(slot_key="landing:overlay-drop")
        asset.image.save("drop.png", image_upload, save=True)
        assert "landing:overlay-drop" in studio_client.get(LANDING).json()["media"]

        studio_client.delete(f"/api/v1/studio/rows/cms.mediaasset/{asset.pk}/")
        assert "landing:overlay-drop" not in studio_client.get(LANDING).json()["media"]

    def test_staged_copy_delete_removes_the_key(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="overlay-drop-copy", text="x")
        studio_client.delete(f"/api/v1/studio/rows/cms.copyblock/{row.pk}/")
        assert "overlay-drop-copy" not in studio_client.get(LANDING).json()["copy"]

    def test_seo_draft_previews(self, studio_client):
        PageSEO.objects.update_or_create(page_key="landing", defaults={"title": "Old"})
        studio_client.put("/api/v1/studio/seo/landing/", {"title": "New title"}, format="json")
        assert studio_client.get(LANDING).json()["seo"]["title"] == "New title"
