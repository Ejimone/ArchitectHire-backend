"""Collections: the generic records API and the draft engine over registry models."""

import pytest

from apps.catalog.models import ProjectType, Service, ServiceCategory
from apps.cms.models_editorial import (
    CaseStudy,
    CaseStudyImage,
    ContactMethod,
    ContactSubmission,
    InspirationItem,
    JobPosting,
    PolicyPage,
    PolicySection,
)
from apps.jurisdictions.models import City, State
from apps.payments.models import SubscriptionPlan
from apps.studio_api import drafts as engine
from apps.studio_api.models import ContentDraft, ContentRevision
from apps.studio_api.registry import BY_LABEL, SPECS, image_labels, parent_of, spec_for

RECORDS = "/api/v1/studio/records/"
ROWS = "/api/v1/studio/rows/"


class TestRegistry:
    def test_every_spec_is_internally_consistent(self):
        for spec in SPECS:
            names = {f.name for f in spec.model._meta.fields}
            assert spec.title_field in names, spec.label
            assert set(spec.search_fields) <= names, spec.label
            assert set(spec.json_shapes) <= names, spec.label
            for child in spec.children:
                assert BY_LABEL[child].parent, child
                assert parent_of(BY_LABEL[child]) is spec
        assert spec_for("case-studies") is spec_for("cms.casestudy")
        assert spec_for("nope") is None
        assert parent_of(BY_LABEL["cms.casestudy"]) is None
        assert "cms.casestudyimage" in image_labels()

    def test_derived_flags(self):
        assert BY_LABEL["cms.jobposting"].orderable and BY_LABEL["cms.jobposting"].publishable
        assert not BY_LABEL["cms.policypage"].orderable
        assert BY_LABEL["cms.contactsubmission"].readonly
        assert BY_LABEL["cms.casestudy"].page_key(CaseStudy(slug="adu")) == "case-study:adu"
        assert BY_LABEL["cms.casestudy"].page_key(CaseStudy(slug="")) is None
        assert BY_LABEL["cms.perk"].page_key(object()) is None

    def test_routes(self):
        assert BY_LABEL["cms.policypage"].route(PolicyPage(slug="terms")) == "/terms"
        assert BY_LABEL["cms.policypage"].route(PolicyPage(slug="cookies")) is None
        assert BY_LABEL["cms.casestudy"].route(CaseStudy(slug="")) is None
        assert (
            BY_LABEL["payments.subscriptionplan"].route(SubscriptionPlan(group="pricing-page"))
            == "/for-experts/pricing"
        )
        assert (
            BY_LABEL["payments.subscriptionplan"].route(SubscriptionPlan(group="standard"))
            == "/for-experts#pricing"
        )
        assert BY_LABEL["jurisdictions.state"].route(State(code="")) is None
        assert BY_LABEL["jurisdictions.city"].route(City(slug="")) is None
        assert BY_LABEL["catalog.projecttype"].route(ProjectType(slug="")) is None
        assert BY_LABEL["cms.inspirationitem"].route(InspirationItem()) == "/inspiration"


@pytest.mark.django_db
class TestScopes:
    def test_record_scopes_land_on_their_pages(self):
        assert engine.scope_for("cms.jobposting", {"title": "x"}) == "careers"
        assert engine.scope_for("cms.casestudy", {"slug": "adu"}) == "case-study:adu"
        assert engine.scope_for("cms.casestudy", {}) == "case-study"
        assert engine.scope_for("jurisdictions.state", {"code": "CA"}) == "state:CA"
        assert engine.scope_for("cms.policypage", {"slug": "terms"}) == "terms"
        assert engine.scope_for("cms.policypage", {}) == "privacy"
        assert engine.scope_for("payments.subscriptionplan", {"group": "pricing-page"}) == (
            "expert-pricing"
        )
        assert engine.scope_for("payments.subscriptionplan", {"group": "standard"}) == (
            "for-experts"
        )
        assert engine.scope_for("accounts.user", {}) == ""

    def test_a_child_takes_its_parents_scope(self):
        study = CaseStudy.objects.create(slug="probe-study", title="Probe")
        assert engine.scope_for("cms.casestudyimage", {"case_study": study.pk}) == (
            "case-study:probe-study"
        )
        assert engine.scope_for("cms.casestudyimage", {"case_study": 999999}) == ""
        assert engine.scope_for("cms.casestudyimage", {}) == ""


@pytest.mark.django_db
class TestRecordsIndex:
    def test_lists_collections_with_counts_and_pending(self, studio_client):
        JobPosting.objects.create(title="Architect", sort_order=0)
        job = JobPosting.objects.first()
        studio_client.patch(f"{ROWS}cms.jobposting/{job.pk}/", {"title": "Senior"}, format="json")
        body = studio_client.get(RECORDS).json()
        sections = {s["section"]: s["collections"] for s in body["sections"]}
        jobs = next(c for c in sections["Company"] if c["label"] == "cms.jobposting")
        assert jobs["count"] >= 1
        assert jobs["pending"] >= 1
        assert jobs["publishable"] is True
        inbox = {c["label"] for c in sections["Inbox"]}
        assert "cms.contactsubmission" in inbox

    def test_unknown_collection_is_a_400(self, studio_client):
        assert studio_client.get(f"{RECORDS}nope/").status_code == 400


@pytest.mark.django_db
class TestRecordList:
    def test_edit_shape_overlays_drafts_and_paginates(self, studio_client):
        for i in range(3):
            ContactMethod.objects.create(kind="SUPPORT", title=f"Method {i}", sort_order=i)
        rows = list(ContactMethod.objects.filter(title__startswith="Method").order_by("sort_order"))
        studio_client.patch(
            f"{ROWS}cms.contactmethod/{rows[0].pk}/", {"title": "Renamed"}, format="json"
        )
        studio_client.delete(f"{ROWS}cms.contactmethod/{rows[1].pk}/")
        studio_client.post(
            f"{ROWS}cms.contactmethod/", {"kind": "SUPPORT", "title": "Brand new"}, format="json"
        )

        body = studio_client.get(f"{RECORDS}cms.contactmethod/?q=Method&page_size=50").json()
        titles = {row["title"]: row for row in body["results"]}
        assert "Method 1" not in titles  # pending delete is hidden in draft mode
        assert titles["Renamed"]["pending"] == "update"
        assert body["collection"]["label"] == "cms.contactmethod"

        # Pending creates are appended (search does not apply to them; they are not rows yet).
        everything = studio_client.get(f"{RECORDS}contact-methods/?page_size=100").json()
        created = [r for r in everything["results"] if r["title"] == "Brand new"]
        assert created and created[0]["id"] < 0 and created[0]["pending"] == "create"

        live = studio_client.get(f"{RECORDS}cms.contactmethod/?q=Method&mode=live").json()
        assert {r["title"] for r in live["results"]} >= {"Method 0", "Method 1", "Method 2"}

        paged = studio_client.get(f"{RECORDS}cms.contactmethod/?q=Method&page_size=2&page=2").json()
        assert paged["page"] == 2 and paged["count"] >= 3

    def test_ordering_param_is_validated(self, studio_client):
        InspirationItem.objects.create(title="B item", sort_order=1)
        InspirationItem.objects.create(title="A item", sort_order=2)
        body = studio_client.get(f"{RECORDS}cms.inspirationitem/?ordering=title&q=item").json()
        assert [r["title"] for r in body["results"]][:2] == ["A item", "B item"]
        bogus = studio_client.get(f"{RECORDS}cms.inspirationitem/?ordering=nope&q=item").json()
        assert bogus["count"] >= 2

    def test_public_shape_runs_the_site_serializer(self, studio_client):
        study = CaseStudy.objects.create(slug="pub-shape", title="Public shape", location="Oakland")
        CaseStudyImage.objects.create(case_study=study, image="cms/case-studies/gallery/x.webp")
        body = studio_client.get(f"{RECORDS}cms.casestudy/?shape=public&q=Public+shape").json()
        row = body["results"][0]
        assert row["id"] == study.pk
        assert row["title"] == "Public shape"
        assert len(row["gallery"]) == 1  # nested children come through
        assert row["gallery"][0]["id"] == study.gallery.first().pk  # …with their ids

    def test_children_can_be_listed_by_parent(self, studio_client):
        page = PolicyPage.objects.create(slug="probe-policy", title="Probe")
        PolicySection.objects.create(page=page, anchor="a", heading="A", body="x")
        other = PolicyPage.objects.create(slug="probe-policy-2", title="Probe 2")
        PolicySection.objects.create(page=other, anchor="b", heading="B", body="x")
        body = studio_client.get(f"{RECORDS}cms.policysection/?parent={page.pk}").json()
        assert [r["heading"] for r in body["results"]] == ["A"]
        # A pending create under the *other* page must not leak into this parent's list.
        studio_client.post(
            f"{ROWS}cms.policysection/",
            {"page": other.pk, "anchor": "c", "heading": "C", "body": "x"},
            format="json",
        )
        body = studio_client.get(f"{RECORDS}cms.policysection/?parent={page.pk}").json()
        assert [r["heading"] for r in body["results"]] == ["A"]
        mine = studio_client.get(f"{RECORDS}cms.policysection/?parent={other.pk}").json()
        assert [r["heading"] for r in mine["results"]] == ["B", "C"]

    def test_readonly_collections_are_readable_but_not_writable(self, studio_client):
        ContactSubmission.objects.create(name="Jo", email="jo@example.com", message="Hi there")
        body = studio_client.get(f"{RECORDS}cms.contactsubmission/?q=jo@example").json()
        assert body["results"][0]["email"] == "jo@example.com"
        refused = studio_client.post(
            f"{ROWS}cms.contactsubmission/",
            {"name": "x", "email": "x@x.io", "message": "m"},
            format="json",
        )
        assert refused.status_code == 400
        assert "not editable" in refused.json()["detail"]

    def test_a_collection_without_a_serializer_falls_back_to_the_snapshot(self, studio_client):
        SubscriptionPlan.objects.create(
            group="standard", key="probe", name="Probe", price_monthly=1
        )
        body = studio_client.get(f"{RECORDS}payments.subscriptionplan/?shape=public&q=Probe").json()
        assert body["results"][0]["name"] == "Probe"


@pytest.mark.django_db
class TestRecordDetail:
    def test_detail_carries_children_choices_schema_and_public(self, studio_client, image_upload):
        from apps.cms.models_editorial import CaseStudyCategory

        category = CaseStudyCategory.objects.create(name="Probe cat", slug="probe-cat")
        study = CaseStudy.objects.create(slug="detail-probe", title="Detail probe")
        image = CaseStudyImage.objects.create(
            case_study=study, image="cms/case-studies/gallery/a.webp", caption="Before"
        )
        # A staged child edit and a staged child create both show up under the parent.
        studio_client.patch(
            f"{ROWS}cms.casestudyimage/{image.pk}/", {"caption": "After"}, format="json"
        )
        upload = studio_client.post(
            "/api/v1/studio/uploads/",
            {"model_label": "cms.casestudyimage", "field": "image", "file": image_upload},
            format="multipart",
        ).json()
        created = studio_client.post(
            f"{ROWS}cms.casestudyimage/",
            {"case_study": study.pk, "image": upload["name"], "caption": "New"},
            format="json",
        )
        assert created.status_code == 200, created.content

        body = studio_client.get(f"{RECORDS}cms.casestudy/{study.pk}/").json()
        assert body["record"]["title"] == "Detail probe"
        assert body["record"]["files"]["hero_image"] is None
        gallery = body["children"]["cms.casestudyimage"]
        assert [g["caption"] for g in gallery] == ["After", "New"]
        assert gallery[1]["id"] < 0
        assert [g["caption"] for g in body["public"]["gallery"]] == ["After", "New"]
        assert "category" in body["choices"]
        assert any(f["name"] == "glance" and "json_shape" in f for f in body["schema"]) is False
        assert category.pk in {c["id"] for c in body["choices"]["category"]}

        live = studio_client.get(f"{RECORDS}cms.casestudy/{study.pk}/?mode=live").json()
        assert [g["caption"] for g in live["children"]["cms.casestudyimage"]] == ["Before"]

    def test_a_pending_create_is_readable_by_its_negative_id(self, studio_client):
        response = studio_client.post(
            f"{ROWS}cms.jobposting/", {"title": "Ghost role"}, format="json"
        )
        canvas_id = response.json()["object_id"]
        body = studio_client.get(f"{RECORDS}cms.jobposting/{canvas_id}/").json()
        assert body["record"]["title"] == "Ghost role"
        assert body["record"]["pending"] == "create"
        assert body["record"]["route"] is None
        assert studio_client.get(f"{RECORDS}cms.jobposting/-999999/").status_code == 404
        assert studio_client.get(f"{RECORDS}cms.jobposting/999999/").status_code == 404

    def test_a_pending_update_and_delete_are_reflected(self, studio_client):
        job = JobPosting.objects.create(title="Live title")
        studio_client.patch(
            f"{ROWS}cms.jobposting/{job.pk}/", {"title": "Draft title"}, format="json"
        )
        assert studio_client.get(f"{RECORDS}cms.jobposting/{job.pk}/").json()["record"][
            "title"
        ] == ("Draft title")
        studio_client.delete(f"{ROWS}cms.jobposting/{job.pk}/")
        body = studio_client.get(f"{RECORDS}cms.jobposting/{job.pk}/").json()
        assert body["record"]["pending"] == "delete"
        assert body["record"]["title"] == "Live title"

    def test_a_row_with_no_title_gets_a_generic_one(self, studio_client):
        section = PolicySection.objects.create(
            page=PolicyPage.objects.create(slug="untitled-probe", title="P"),
            anchor="x",
            heading="",
            body="b",
        )
        body = studio_client.get(f"{RECORDS}cms.policysection/{section.pk}/").json()
        assert body["record"]["title"] == f"Policy section #{section.pk}"


@pytest.mark.django_db
class TestPublishRecords:
    def test_publish_one_record_takes_its_children_along(self, studio_client):
        study = CaseStudy.objects.create(slug="pub-record", title="Before")
        image = CaseStudyImage.objects.create(case_study=study, image="cms/x.webp", caption="c")
        other = JobPosting.objects.create(title="Untouched")
        studio_client.patch(f"{ROWS}cms.casestudy/{study.pk}/", {"title": "After"}, format="json")
        studio_client.patch(
            f"{ROWS}cms.casestudyimage/{image.pk}/", {"caption": "d"}, format="json"
        )
        studio_client.post(
            f"{ROWS}cms.casestudyimage/",
            {"case_study": study.pk, "image": "cms/y.webp"},
            format="json",
        )
        studio_client.patch(
            f"{ROWS}cms.jobposting/{other.pk}/", {"title": "Still pending"}, format="json"
        )

        response = studio_client.post(
            "/api/v1/studio/publish/",
            {"model_label": "cms.casestudy", "object_id": study.pk},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["published"] == 3
        study.refresh_from_db()
        assert study.title == "After"
        assert study.gallery.count() == 2
        assert ContentDraft.objects.filter(model_label="cms.jobposting").exists()

    def test_publish_a_pending_create_by_its_canvas_id(self, studio_client):
        canvas_id = studio_client.post(
            f"{ROWS}cms.department/", {"name": "Probe dept"}, format="json"
        ).json()["object_id"]
        response = studio_client.post(
            "/api/v1/studio/publish/",
            {"model_label": "cms.department", "object_id": canvas_id},
            format="json",
        )
        assert response.json()["published"] == 1

    def test_deleting_a_parent_snapshots_its_children_and_revert_restores_them(self, studio_client):
        page = PolicyPage.objects.create(slug="cascade-probe", title="Cascade")
        PolicySection.objects.create(page=page, anchor="one", heading="One", body="1")
        PolicySection.objects.create(page=page, anchor="two", heading="Two", body="2")
        response = studio_client.delete(f"{ROWS}cms.policypage/{page.pk}/?mode=live")
        assert response.status_code == 200
        assert not PolicyPage.objects.filter(pk=page.pk).exists()
        revision = ContentRevision.objects.get(pk=response.json()["revision"])
        assert [c["model_label"] for c in revision.changes] == [
            "cms.policysection",
            "cms.policysection",
            "cms.policypage",
        ]
        studio_client.post(f"/api/v1/studio/revisions/{revision.pk}/revert/")
        restored = PolicyPage.objects.get(pk=page.pk)
        assert sorted(restored.sections.values_list("anchor", flat=True)) == ["one", "two"]

    def test_a_child_cannot_be_added_under_a_missing_parent(self, studio_client):
        response = studio_client.post(
            f"{ROWS}catalog.service/",
            {"category": -5, "name": "Ghost", "slug": "ghost", "price_display": "$1"},
            format="json",
        )
        assert response.status_code == 400
        assert "category" in response.json()["errors"]

    def test_a_new_service_lands_after_its_siblings_in_its_category(self, studio_client):
        category = ServiceCategory.objects.create(name="Order cat", slug="order-cat")
        Service.objects.create(
            category=category, name="A", slug="order-a", price_display="$1", sort_order=4
        )
        response = studio_client.post(
            f"{ROWS}catalog.service/?mode=live",
            {"category": category.pk, "name": "B", "slug": "order-b", "price_display": "$2"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert Service.objects.get(slug="order-b").sort_order == 5


@pytest.mark.django_db
def test_schema_describes_collections(studio_client):
    body = studio_client.get("/api/v1/studio/schema/").json()
    case = body["models"]["cms.casestudy"]
    assert case["record"]["children"] == ["cms.casestudyimage"]
    glance = next(f for f in case["fields"] if f["name"] == "glance")
    assert glance["json_shape"]["kind"] == "list"
    inbox = body["models"]["cms.contactsubmission"]
    assert all(f.get("readonly") for f in inbox["fields"])
    assert body["models"]["catalog.service"]["record"]["parent"] == "category"
