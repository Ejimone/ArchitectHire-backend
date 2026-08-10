"""CMS content API tests.

NOTE: other test modules run `manage.py seed` at module scope, and that data
persists in the shared test database. These tests therefore assert on their own
uniquely-named rows rather than on absolute counts or index positions.
"""

import pytest

from apps.cms.models import (
    FAQ,
    FooterColumn,
    FooterLink,
    NavGroup,
    NavItem,
    PageSEO,
    SiteSettings,
    Stat,
)

PAGE_URL = "/api/v1/content/pages/landing/"


@pytest.mark.django_db
class TestPageContent:
    def test_anonymous_can_read(self, api_client):
        response = api_client.get(PAGE_URL)
        assert response.status_code == 200
        body = response.json()
        assert body["page"] == "landing"
        assert "settings" in body
        assert "blocks" in body
        assert "copy" in body

    def test_unknown_page_404(self, api_client):
        assert api_client.get("/api/v1/content/pages/not-a-page/").status_code == 404

    def test_blocks_are_scoped_published_and_ordered(self, api_client):
        FAQ.objects.create(scope="landing", question="QA-Second?", answer="B", sort_order=9902)
        FAQ.objects.create(scope="landing", question="QA-First?", answer="A", sort_order=9901)
        FAQ.objects.create(scope="landing", question="QA-Hidden?", answer="X", status="draft")
        FAQ.objects.create(scope="services", question="QA-Other page?", answer="C")
        Stat.objects.create(scope="landing", value="3,200+", label="jurisdictions scored")

        body = api_client.get(PAGE_URL).json()
        faqs = body["blocks"]["faqs"]
        questions = [f["question"] for f in faqs if f["question"].startswith("QA-")]
        assert questions == ["QA-First?", "QA-Second?"]
        assert any(s["value"] == "3,200+" for s in body["blocks"]["stats"])
        all_questions = [f["question"] for f in body["blocks"]["faqs"]]
        assert "QA-Hidden?" not in all_questions
        assert "QA-Other page?" not in all_questions

    def test_seo_payload(self, api_client):
        PageSEO.objects.update_or_create(
            page_key="landing",
            defaults={
                "title": "Hire a licensed architect",
                "description": "Stamped drawings, remotely.",
            },
        )
        body = api_client.get(PAGE_URL).json()
        assert body["seo"]["title"] == "Hire a licensed architect"

    def test_settings_included(self, api_client):
        settings_obj = SiteSettings.get_solo()
        settings_obj.promo_banner_text = "Get matched in 48 hours"
        settings_obj.save()
        body = api_client.get(PAGE_URL).json()
        assert body["settings"]["promo_banner_text"] == "Get matched in 48 hours"

    def test_cache_busts_on_new_content(self, api_client):
        api_client.get(PAGE_URL)  # warm the cache
        FAQ.objects.create(scope="landing", question="QA-Fresh?", answer="Yes")
        second = api_client.get(PAGE_URL).json()
        assert "QA-Fresh?" in [f["question"] for f in second["blocks"]["faqs"]]

    def test_etag_304(self, api_client):
        response = api_client.get(PAGE_URL)
        etag = response.headers["ETag"]
        assert response.headers["Cache-Control"].startswith("public")
        cached = api_client.get(PAGE_URL, HTTP_IF_NONE_MATCH=etag)
        assert cached.status_code == 304

    def test_etag_changes_after_edit(self, api_client):
        etag_before = api_client.get(PAGE_URL).headers["ETag"]
        FAQ.objects.create(scope="landing", question="QA-New?", answer="Y")
        etag_after = api_client.get(PAGE_URL).headers["ETag"]
        assert etag_before != etag_after


@pytest.mark.django_db
class TestNavFooter:
    def test_nav_grouped_by_menu(self, api_client):
        group = NavGroup.objects.create(menu="services", heading="QA Group")
        NavItem.objects.create(
            group=group, label="QA consult", href="/services/consult", price_hint="$145"
        )
        body = api_client.get("/api/v1/content/nav/").json()
        qa_group = next(g for g in body["menus"]["services"] if g["heading"] == "QA Group")
        assert qa_group["items"][0]["label"] == "QA consult"
        assert qa_group["items"][0]["price_hint"] == "$145"

    def test_footer_columns(self, api_client):
        column = FooterColumn.objects.create(heading="QA Column")
        FooterLink.objects.create(column=column, label="QA drafting", href="/services/cad-drafting")
        body = api_client.get("/api/v1/content/footer/").json()
        qa_column = next(c for c in body["columns"] if c["heading"] == "QA Column")
        assert qa_column["links"][0]["label"] == "QA drafting"

    def test_settings_endpoint(self, api_client):
        assert api_client.get("/api/v1/content/settings/").status_code == 200
