"""Publishing, live mode, and rollback."""

import pytest

from apps.cms.models import FAQ, CopyBlock, PageSEO
from apps.studio_api import drafts as engine
from apps.studio_api.models import ContentDraft, ContentRevision

LANDING = "/api/v1/studio/pages/landing/"
PUBLIC_LANDING = "/api/v1/content/pages/landing/"
PUBLISH = "/api/v1/studio/publish/"
QUEUE = "/api/v1/studio/queue/"
DISCARD = "/api/v1/studio/discard/"
REVISIONS = "/api/v1/studio/revisions/"


@pytest.mark.django_db
class TestQueue:
    def test_queue_groups_pending_edits_by_page(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="queue-probe", text="x")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "y"}, format="json"
        )
        body = studio_client.get(QUEUE).json()
        landing = next(s for s in body["scopes"] if s["scope"] == "landing")
        assert landing["route"] == "/"
        assert any(c["model_label"] == "cms.copyblock" for c in landing["changes"])
        assert body["total"] >= 1

    def test_discard_drops_drafts_without_touching_the_site(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="discard-probe", text="Before")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "After"}, format="json"
        )
        assert (
            studio_client.post(DISCARD, {"scope": "landing"}, format="json").json()["discarded"]
            >= 1
        )
        row.refresh_from_db()
        assert row.text == "Before"


@pytest.mark.django_db
class TestPublish:
    def test_publishing_applies_every_kind_of_edit(self, studio_client, api_client):
        edited = CopyBlock.objects.create(scope="landing", key="pub-copy", text="Before")
        doomed = FAQ.objects.create(scope="landing", question="Doomed?", answer="A")

        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{edited.pk}/", {"text": "After"}, format="json"
        )
        studio_client.post(
            "/api/v1/studio/rows/cms.faq/",
            {"scope": "landing", "question": "Brand new?", "answer": "Yes"},
            format="json",
        )
        studio_client.delete(f"/api/v1/studio/rows/cms.faq/{doomed.pk}/")

        response = studio_client.post(PUBLISH, {"scope": "landing"}, format="json")
        assert response.status_code == 200
        assert response.json()["published"] == 3

        public = api_client.get(PUBLIC_LANDING).json()
        assert public["copy"]["pub-copy"]["text"] == "After"
        questions = [f["question"] for f in public["blocks"]["faqs"]]
        assert "Brand new?" in questions
        assert "Doomed?" not in questions
        assert not ContentDraft.objects.filter(scope="landing").exists()

    def test_publishing_nothing_is_a_no_op(self, studio_client):
        studio_client.post(DISCARD, {}, format="json")
        body = studio_client.post(PUBLISH, {}, format="json").json()
        assert body == {"published": 0, "revision": None}

    def test_publish_can_target_specific_drafts(self, studio_client):
        one = CopyBlock.objects.create(scope="landing", key="pub-one", text="a")
        two = CopyBlock.objects.create(scope="landing", key="pub-two", text="a")
        for row in (one, two):
            studio_client.patch(
                f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "b"}, format="json"
            )
        target = ContentDraft.objects.get(model_label="cms.copyblock", object_id=one.pk)
        studio_client.post(PUBLISH, {"ids": [target.pk]}, format="json")

        one.refresh_from_db()
        two.refresh_from_db()
        assert one.text == "b"
        assert two.text == "a"

    def test_a_row_deleted_before_publish_is_skipped(self, studio_client):
        faq = FAQ.objects.create(scope="landing", question="Ghost?", answer="A")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.faq/{faq.pk}/", {"answer": "B"}, format="json"
        )
        FAQ.objects.filter(pk=faq.pk).delete()
        body = studio_client.post(PUBLISH, {"scope": "landing"}, format="json").json()
        assert body["published"] == 1
        assert ContentRevision.objects.get(pk=body["revision"]).changes == []


@pytest.mark.django_db
class TestLiveMode:
    def test_live_edit_reaches_the_site_without_publishing(self, studio_client, api_client):
        row = CopyBlock.objects.create(scope="landing", key="live-copy", text="Before")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/?mode=live",
            {"text": "Live now"},
            format="json",
        )
        assert response.json()["mode"] == "live"
        assert not ContentDraft.objects.filter(object_id=row.pk).exists()
        assert api_client.get(PUBLIC_LANDING).json()["copy"]["live-copy"]["text"] == "Live now"

    def test_live_edits_still_land_in_history(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="live-history", text="Before")
        response = studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/?mode=live",
            {"text": "After"},
            format="json",
        )
        revision = ContentRevision.objects.get(pk=response.json()["revision"])
        assert revision.scope == "landing"
        assert revision.changes[0]["before"]["text"] == "Before"

    def test_live_create_and_delete(self, studio_client):
        created = studio_client.post(
            "/api/v1/studio/rows/cms.faq/?mode=live",
            {"scope": "landing", "question": "Live create?", "answer": "Y"},
            format="json",
        ).json()
        assert FAQ.objects.filter(pk=created["object_id"]).exists()

        studio_client.delete(f"/api/v1/studio/rows/cms.faq/{created['object_id']}/?mode=live")
        assert not FAQ.objects.filter(pk=created["object_id"]).exists()

    def test_live_edit_of_a_missing_row_is_a_400(self, studio_client):
        response = studio_client.patch(
            "/api/v1/studio/rows/cms.faq/99999999/?mode=live", {"answer": "x"}, format="json"
        )
        assert response.status_code == 400

    def test_live_reorder_is_one_revision(self, studio_client):
        first = FAQ.objects.create(scope="landing", question="LRO-1?", answer="A", sort_order=1)
        second = FAQ.objects.create(scope="landing", question="LRO-2?", answer="B", sort_order=2)
        before = ContentRevision.objects.count()
        studio_client.post(
            "/api/v1/studio/rows/cms.faq/reorder/?mode=live",
            {"ids": [second.pk, first.pk]},
            format="json",
        )
        assert ContentRevision.objects.count() == before + 1
        second.refresh_from_db()
        assert second.sort_order == 0


@pytest.mark.django_db
class TestRevert:
    def test_revert_undoes_all_three_operations(self, studio_client, api_client):
        edited = CopyBlock.objects.create(scope="landing", key="rev-copy", text="Original")
        doomed = FAQ.objects.create(scope="landing", question="Rev doomed?", answer="A")

        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{edited.pk}/", {"text": "Changed"}, format="json"
        )
        created = studio_client.post(
            "/api/v1/studio/rows/cms.faq/",
            {"scope": "landing", "question": "Rev created?", "answer": "Y"},
            format="json",
        )
        studio_client.delete(f"/api/v1/studio/rows/cms.faq/{doomed.pk}/")
        published = studio_client.post(PUBLISH, {"scope": "landing"}, format="json").json()

        assert (
            studio_client.post(
                f"/api/v1/studio/revisions/{published['revision']}/revert/"
            ).status_code
            == 200
        )

        edited.refresh_from_db()
        assert edited.text == "Original"
        # The deleted row comes back with its original id, so links to it still resolve.
        assert FAQ.objects.filter(pk=doomed.pk, question="Rev doomed?").exists()
        assert not FAQ.objects.filter(question="Rev created?").exists()
        assert created.status_code == 200

    def test_a_revision_cannot_be_reverted_twice(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="rev-twice", text="a")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "b"}, format="json"
        )
        revision = studio_client.post(PUBLISH, {"scope": "landing"}, format="json").json()[
            "revision"
        ]
        studio_client.post(f"/api/v1/studio/revisions/{revision}/revert/")
        assert studio_client.post(f"/api/v1/studio/revisions/{revision}/revert/").status_code == 400

    def test_reverting_an_unknown_revision_404s(self, studio_client):
        assert studio_client.post("/api/v1/studio/revisions/9999999/revert/").status_code == 404

    def test_revert_skips_rows_that_vanished(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="rev-vanish", text="a")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/", {"text": "b"}, format="json"
        )
        published = studio_client.post(PUBLISH, {"scope": "landing"}, format="json").json()
        CopyBlock.objects.filter(pk=row.pk).delete()
        assert (
            studio_client.post(
                f"/api/v1/studio/revisions/{published['revision']}/revert/"
            ).status_code
            == 200
        )

    def test_revert_of_a_create_whose_row_is_gone_is_skipped(self, studio_client):
        created = studio_client.post(
            "/api/v1/studio/rows/cms.faq/?mode=live",
            {"scope": "landing", "question": "Gone create?", "answer": "Y"},
            format="json",
        ).json()
        FAQ.objects.filter(pk=created["object_id"]).delete()
        assert (
            studio_client.post(
                f"/api/v1/studio/revisions/{created['revision']}/revert/"
            ).status_code
            == 200
        )

    def test_history_lists_revisions_for_a_page(self, studio_client):
        row = CopyBlock.objects.create(scope="landing", key="rev-list", text="a")
        studio_client.patch(
            f"/api/v1/studio/rows/cms.copyblock/{row.pk}/?mode=live", {"text": "b"}, format="json"
        )
        body = studio_client.get(f"{REVISIONS}?scope=landing").json()
        assert body["revisions"]
        assert body["revisions"][0]["scope"] == "landing"
        assert body["revisions"][0]["rows"] == 1

    def test_history_is_unfiltered_by_default(self, studio_client):
        assert "revisions" in studio_client.get(REVISIONS).json()


@pytest.mark.django_db
class TestEngineDirectly:
    """Paths the HTTP layer cannot reach."""

    def test_unknown_model_is_refused(self):
        with pytest.raises(engine.DraftError):
            engine.resolve_model("auth.user")

    def test_staging_a_missing_row_is_refused(self, db):
        with pytest.raises(engine.DraftError):
            engine.stage(model_label="cms.faq", op=ContentDraft.Op.UPDATE, object_id=99999999)

    def test_delete_supersedes_a_pending_update(self, db):
        faq = FAQ.objects.create(scope="landing", question="Supersede?", answer="A")
        engine.stage(
            model_label="cms.faq",
            op=ContentDraft.Op.UPDATE,
            object_id=faq.pk,
            payload={"answer": "B"},
        )
        engine.stage(model_label="cms.faq", op=ContentDraft.Op.DELETE, object_id=faq.pk)
        draft = ContentDraft.objects.get(model_label="cms.faq", object_id=faq.pk)
        assert draft.op == ContentDraft.Op.DELETE
        assert draft.payload == {}

    def test_editing_a_row_already_staged_for_deletion_is_ignored(self, db):
        faq = FAQ.objects.create(scope="landing", question="Already doomed?", answer="A")
        engine.stage(model_label="cms.faq", op=ContentDraft.Op.DELETE, object_id=faq.pk)
        draft = engine.stage(
            model_label="cms.faq",
            op=ContentDraft.Op.UPDATE,
            object_id=faq.pk,
            payload={"answer": "B"},
        )
        assert draft.op == ContentDraft.Op.DELETE

    def test_repeated_edits_merge_into_one_draft(self, db):
        faq = FAQ.objects.create(scope="landing", question="Merge?", answer="A")
        engine.stage(
            model_label="cms.faq",
            op=ContentDraft.Op.UPDATE,
            object_id=faq.pk,
            payload={"answer": "B"},
        )
        engine.stage(
            model_label="cms.faq",
            op=ContentDraft.Op.UPDATE,
            object_id=faq.pk,
            payload={"question": "Merged?"},
        )
        drafts = ContentDraft.objects.filter(model_label="cms.faq", object_id=faq.pk)
        assert drafts.count() == 1
        assert drafts.first().payload == {"answer": "B", "question": "Merged?"}

    def test_canvas_id_lookup_ignores_real_ids(self, db):
        assert engine.draft_for_canvas_id("cms.faq", 5) is None

    def test_scope_of_a_media_slot_splits_from_the_right(self):
        assert engine.media_scope("city:oakland:work-1") == "city:oakland"
        assert engine.scope_for("cms.mediaasset", {"slot_key": "landing:hero"}) == "landing"
        assert engine.scope_for("cms.pageseo", {"page_key": "about"}) == "about"
        assert engine.scope_for("cms.navitem", {}) == ""

    def test_apply_now_many_with_nothing_to_do(self, db):
        assert engine.apply_now_many([]) is None

    def test_publish_of_an_empty_set_returns_nothing(self, db):
        assert engine.publish([]) is None

    def test_draft_and_revision_reprs(self, db):
        faq = FAQ.objects.create(scope="landing", question="Repr?", answer="A")
        draft = engine.stage(
            model_label="cms.faq", op=ContentDraft.Op.UPDATE, object_id=faq.pk, payload={}
        )
        assert "cms.faq" in str(draft)
        pending = engine.stage(
            model_label="cms.faq",
            op=ContentDraft.Op.CREATE,
            payload={"scope": "landing", "question": "New?"},
        )
        assert "new#" in str(pending)
        revision = engine.publish([draft, pending], scope="landing")
        assert "landing" in str(revision)
        assert revision.summary

    def test_summary_of_an_empty_change_set(self):
        assert engine._summarise([]) == "No changes"

    def test_seo_create_when_no_row_exists(self, studio_client, db):
        PageSEO.objects.filter(page_key="about").delete()
        response = studio_client.put(
            "/api/v1/studio/seo/about/?mode=live", {"title": "About us"}, format="json"
        )
        assert response.status_code == 200
        assert PageSEO.objects.get(page_key="about").title == "About us"
