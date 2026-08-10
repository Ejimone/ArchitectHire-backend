import pytest
from django.utils import timezone

from apps.cms.models import (
    Author,
    BlogCategory,
    BlogContentBlock,
    BlogPost,
    CaseStudy,
    ContactTopic,
    InspirationItem,
    NewsletterSubscriber,
    PolicyPage,
    PolicySection,
)


def make_post(slug, **kwargs):
    defaults = {
        "title": slug.replace("-", " ").title(),
        "status": "published",
        "published_at": timezone.now(),
    }
    defaults.update(kwargs)
    return BlogPost.objects.create(slug=slug, **defaults)


@pytest.mark.django_db
class TestBlogAPI:
    def test_list_with_categories_and_featured(self, api_client):
        category = BlogCategory.objects.create(name="QA-Permits", slug="qa-permits")
        make_post("qa-featured", category=category, is_featured=True)
        make_post("qa-regular", category=category)
        make_post("qa-draft", status="draft")

        body = api_client.get("/api/v1/content/blog/").json()
        slugs = [p["slug"] for p in body["results"]]
        assert "qa-featured" in slugs and "qa-regular" in slugs
        assert "qa-draft" not in slugs
        assert body["featured"]["slug"] == "qa-featured"
        assert any(c["slug"] == "qa-permits" for c in body["categories"])

    def test_category_filter(self, api_client):
        cat_a = BlogCategory.objects.create(name="QA-A", slug="qa-a")
        cat_b = BlogCategory.objects.create(name="QA-B", slug="qa-b")
        make_post("qa-in-a", category=cat_a)
        make_post("qa-in-b", category=cat_b)
        body = api_client.get("/api/v1/content/blog/?category=qa-a").json()
        slugs = [p["slug"] for p in body["results"]]
        assert "qa-in-a" in slugs and "qa-in-b" not in slugs

    def test_detail_with_blocks_and_related(self, api_client):
        author = Author.objects.create(name="QA Author", role="Architect")
        category = BlogCategory.objects.create(name="QA-Cat", slug="qa-cat")
        post = make_post("qa-article", category=category, author=author)
        BlogContentBlock.objects.create(post=post, kind="h2", text="Section one", sort_order=0)
        BlogContentBlock.objects.create(
            post=post, kind="pullquote", text="Quote!", attribution="Someone", sort_order=1
        )
        make_post("qa-related", category=category)

        body = api_client.get("/api/v1/content/blog/qa-article/").json()
        assert body["author"]["name"] == "QA Author"
        assert [b["kind"] for b in body["content_blocks"]] == ["h2", "pullquote"]
        assert any(r["slug"] == "qa-related" for r in body["related"])


@pytest.mark.django_db
class TestCaseStudyAPI:
    def test_detail_narrative(self, api_client):
        CaseStudy.objects.create(
            slug="qa-adu",
            title="QA ADU",
            status="published",
            published_at=timezone.now(),
            brief="The brief.",
            match_points=["Licensed in CA", "ADU specialist"],
            glance=[{"k": "Project", "v": "ADU"}],
        )
        body = api_client.get("/api/v1/content/case-studies/qa-adu/").json()
        assert body["brief"] == "The brief."
        assert body["match_points"] == ["Licensed in CA", "ADU specialist"]


@pytest.mark.django_db
class TestContactAndNewsletter:
    def test_contact_submission(self, api_client):
        ContactTopic.objects.create(label="QA Topic")
        response = api_client.post(
            "/api/v1/content/contact/",
            {"name": "Jane", "email": "jane@example.com", "topic": "QA Topic", "message": "Hi"},
            format="json",
        )
        assert response.status_code == 201

    def test_contact_unknown_topic_rejected(self, api_client):
        response = api_client.post(
            "/api/v1/content/contact/",
            {"name": "Jane", "email": "jane@example.com", "topic": "Nope", "message": "Hi"},
            format="json",
        )
        assert response.status_code == 400

    def test_newsletter_idempotent(self, api_client):
        for _ in range(2):
            response = api_client.post(
                "/api/v1/content/newsletter/", {"email": "sub@example.com"}, format="json"
            )
            assert response.status_code == 201
        assert NewsletterSubscriber.objects.filter(email="sub@example.com").count() == 1


@pytest.mark.django_db
class TestPolicyAPI:
    def test_policy_sections_with_paragraphs(self, api_client):
        page = PolicyPage.objects.create(slug="qa-privacy", title="Privacy Policy")
        PolicySection.objects.create(
            page=page,
            anchor="collect",
            heading="What we collect",
            body="First paragraph.\n\nSecond paragraph.",
        )
        body = api_client.get("/api/v1/content/policies/qa-privacy/").json()
        assert body["sections"][0]["anchor"] == "collect"
        assert body["sections"][0]["paragraphs"] == ["First paragraph.", "Second paragraph."]


@pytest.mark.django_db
class TestInspirationAPI:
    def test_like_toggle_anonymous(self, api_client):
        item = InspirationItem.objects.create(
            title="QA Loft", status="published", published_at=timezone.now()
        )
        first = api_client.post(f"/api/v1/content/inspiration/{item.pk}/like/").json()
        assert first == {"liked": True, "likes_count": 1}
        second = api_client.post(f"/api/v1/content/inspiration/{item.pk}/like/").json()
        assert second == {"liked": False, "likes_count": 0}


@pytest.mark.django_db
class TestSearchAPI:
    def test_search_groups_results(self, api_client):
        from django.core.management import call_command

        call_command("seed", "--domain", "jurisdictions,catalog,searchindex")
        body = api_client.get("/api/v1/content/search/?q=render").json()
        assert "Services" in body["results"]
        assert any("render" in r["title"].lower() for r in body["results"]["Services"])

    def test_short_query_returns_popular_only(self, api_client):
        body = api_client.get("/api/v1/content/search/?q=a").json()
        assert body["results"] == {}
