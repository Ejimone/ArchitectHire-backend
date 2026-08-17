"""Remaining public content endpoints: media slots, case-study index, careers,
contact GET, inspiration filters and the signed-in like path."""

import pytest
from django.utils import timezone

from apps.accounts.factories import UserFactory
from apps.cms.models import (
    CaseStudy,
    CaseStudyCategory,
    ContactMethod,
    ContactTopic,
    Department,
    InspirationItem,
    JobPosting,
    MediaAsset,
    Perk,
)
from apps.cms.views import CachedContentView


def test_cached_content_view_is_abstract():
    """Subclasses must supply the payload; the base class refuses to guess."""
    with pytest.raises(NotImplementedError):
        CachedContentView().build_payload(None)


@pytest.mark.django_db
class TestMediaSlots:
    def test_all_slots_and_prefix_filter(self, api_client):
        MediaAsset.objects.create(slot_key="qa-landing-hero", image="cms/slots/hero.jpg")
        MediaAsset.objects.create(slot_key="qa-about-team", image="cms/slots/team.jpg")
        MediaAsset.objects.create(slot_key="qa-no-image")  # excluded: no file

        every = api_client.get("/api/v1/content/media/").json()["slots"]
        assert "qa-landing-hero" in every
        assert "qa-about-team" in every
        assert "qa-no-image" not in every

        filtered = api_client.get("/api/v1/content/media/?prefix=qa-landing").json()["slots"]
        assert list(filtered) == ["qa-landing-hero"]

    def test_an_upload_is_visible_immediately(self, api_client):
        """The regression that hid every image the owner ever uploaded.

        This endpoint caches one payload per `?prefix=`, keyed on slug
        `_media:<prefix>`. No tag mapped to that slug, so its version counter never moved
        past 1 — a new upload stayed invisible for the full 15-minute TTL, and because
        the ETag is built from the same frozen version, a client sending If-None-Match
        was told 304 against the empty body indefinitely.
        """
        first = api_client.get("/api/v1/content/media/?prefix=qa-fresh")
        assert "qa-fresh:hero" not in first.json()["slots"]

        MediaAsset.objects.create(slot_key="qa-fresh:hero", image="cms/slots/hero.jpg")

        second = api_client.get("/api/v1/content/media/?prefix=qa-fresh")
        assert "qa-fresh:hero" in second.json()["slots"]
        # A moved version means a new ETag, so conditional requests refetch too.
        assert second["ETag"] != first["ETag"]

    def test_prefixes_share_one_counter_but_keep_separate_payloads(self, api_client):
        """One counter covers every prefix — a save cannot know which variants are
        cached — while each prefix still gets its own cache entry."""
        MediaAsset.objects.create(slot_key="qa-one:hero", image="cms/slots/a.jpg")
        MediaAsset.objects.create(slot_key="qa-two:hero", image="cms/slots/b.jpg")

        one = api_client.get("/api/v1/content/media/?prefix=qa-one")
        two = api_client.get("/api/v1/content/media/?prefix=qa-two")
        assert list(one.json()["slots"]) == ["qa-one:hero"]
        assert list(two.json()["slots"]) == ["qa-two:hero"]
        # Same version, different cache slug -> different ETag, no cross-serving.
        assert one["ETag"] != two["ETag"]

        # A write under one prefix invalidates the other's cached payload as well.
        MediaAsset.objects.create(slot_key="qa-two:extra", image="cms/slots/c.jpg")
        assert api_client.get("/api/v1/content/media/?prefix=qa-one")["ETag"] != one["ETag"]

    def test_results_are_ordered_and_report_truncation(self, api_client, monkeypatch):
        """Without an explicit order_by, *which* rows survive the slice is whatever the
        query planner returns — so a truncated response silently dropped a random tail."""
        from apps.cms.views import MediaSlotsView

        monkeypatch.setattr(MediaSlotsView, "PAGE_SIZE", 2)
        for key in ("qa-order:c", "qa-order:a", "qa-order:b"):
            MediaAsset.objects.create(slot_key=key, image=f"cms/slots/{key[-1]}.jpg")

        body = api_client.get("/api/v1/content/media/?prefix=qa-order").json()
        assert list(body["slots"]) == ["qa-order:a", "qa-order:b"]
        assert body["truncated"] is True

    def test_untruncated_responses_say_so(self, api_client):
        MediaAsset.objects.create(slot_key="qa-small:hero", image="cms/slots/a.jpg")
        body = api_client.get("/api/v1/content/media/?prefix=qa-small").json()
        assert body["truncated"] is False


@pytest.mark.django_db
class TestCaseStudyIndex:
    def _case(self, slug, **kwargs):
        defaults = {
            "title": slug.replace("-", " ").title(),
            "status": "published",
            "published_at": timezone.now(),
        }
        defaults.update(kwargs)
        return CaseStudy.objects.create(slug=slug, **defaults)

    def test_list_with_categories_and_featured(self, api_client):
        category = CaseStudyCategory.objects.create(name="QA-ADU", slug="qa-adu-cat")
        self._case("qa-cs-featured", category=category, is_featured=True)
        self._case("qa-cs-regular", category=category)
        self._case("qa-cs-draft", status="draft")

        body = api_client.get("/api/v1/content/case-studies/").json()
        slugs = [c["slug"] for c in body["results"]]
        assert "qa-cs-featured" in slugs
        assert "qa-cs-draft" not in slugs
        assert body["featured"]["slug"] == "qa-cs-featured"
        assert any(c["slug"] == "qa-adu-cat" for c in body["categories"])

    def test_category_filter(self, api_client):
        cat_a = CaseStudyCategory.objects.create(name="QA-CS-A", slug="qa-cs-a")
        cat_b = CaseStudyCategory.objects.create(name="QA-CS-B", slug="qa-cs-b")
        self._case("qa-cs-in-a", category=cat_a)
        self._case("qa-cs-in-b", category=cat_b)
        body = api_client.get("/api/v1/content/case-studies/?category=qa-cs-a").json()
        slugs = [c["slug"] for c in body["results"]]
        assert "qa-cs-in-a" in slugs
        assert "qa-cs-in-b" not in slugs


@pytest.mark.django_db
class TestCareersAndContact:
    def test_careers_payload(self, api_client):
        department = Department.objects.create(name="QA Engineering")
        Perk.objects.create(title="QA Remote-first")
        JobPosting.objects.create(
            title="QA Backend engineer",
            department=department,
            status="published",
            published_at=timezone.now(),
        )
        body = api_client.get("/api/v1/content/careers/").json()
        assert "QA Engineering" in body["departments"]
        assert any(p["title"] == "QA Remote-first" for p in body["perks"])
        assert any(j["title"] == "QA Backend engineer" for j in body["jobs"])

    def test_contact_methods_and_topics(self, api_client):
        ContactMethod.objects.create(kind="QA-CLIENTS", title="QA Talk to us")
        ContactTopic.objects.create(label="QA Billing")
        body = api_client.get("/api/v1/content/contact/").json()
        assert any(m["title"] == "QA Talk to us" for m in body["methods"])
        assert "QA Billing" in body["topics"]


@pytest.mark.django_db
class TestInspiration:
    def _item(self, title, **kwargs):
        return InspirationItem.objects.create(
            title=title, status="published", published_at=timezone.now(), **kwargs
        )

    def test_tag_style_and_popular_filters(self, api_client):
        self._item("QA Kitchen", tag="qa-kitchen", style="qa-warm", likes_count=1)
        self._item("QA Loft", tag="qa-loft", style="qa-cool", likes_count=99)

        by_tag = api_client.get("/api/v1/content/inspiration/?tag=QA-KITCHEN").json()["results"]
        assert [i["title"] for i in by_tag] == ["QA Kitchen"]

        by_style = api_client.get("/api/v1/content/inspiration/?style=qa-cool").json()["results"]
        assert [i["title"] for i in by_style] == ["QA Loft"]

    def test_popular_sort_orders_by_likes(self, api_client):
        self._item("QA Popular Low", tag="qa-popular", likes_count=5)
        self._item("QA Popular High", tag="qa-popular", likes_count=50)
        results = api_client.get(
            "/api/v1/content/inspiration/?tag=qa-popular&style=all&sort=popular"
        ).json()["results"]
        assert [i["title"] for i in results] == ["QA Popular High", "QA Popular Low"]

    def test_like_unknown_item_404(self, api_client):
        assert api_client.post("/api/v1/content/inspiration/999999/like/").status_code == 404

    def test_like_toggle_for_signed_in_user(self, api_client):
        item = self._item("QA Likeable")
        api_client.force_authenticate(user=UserFactory())
        assert api_client.post(f"/api/v1/content/inspiration/{item.pk}/like/").json() == {
            "liked": True,
            "likes_count": 1,
        }
        assert api_client.post(f"/api/v1/content/inspiration/{item.pk}/like/").json() == {
            "liked": False,
            "likes_count": 0,
        }
