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
        assert body["blocks"] == {}

    def test_unknown_page_404(self, api_client):
        assert api_client.get("/api/v1/content/pages/not-a-page/").status_code == 404

    def test_blocks_are_scoped_published_and_ordered(self, api_client):
        FAQ.objects.create(scope="landing", question="Second?", answer="B", sort_order=2)
        FAQ.objects.create(scope="landing", question="First?", answer="A", sort_order=1)
        FAQ.objects.create(scope="landing", question="Hidden?", answer="X", status="draft")
        FAQ.objects.create(scope="services", question="Other page?", answer="C")
        Stat.objects.create(scope="landing", value="3,200+", label="jurisdictions scored")

        body = api_client.get(PAGE_URL).json()
        questions = [f["question"] for f in body["blocks"]["faqs"]]
        assert questions == ["First?", "Second?"]
        assert body["blocks"]["stats"][0]["value"] == "3,200+"

    def test_seo_payload(self, api_client):
        PageSEO.objects.create(
            page_key="landing",
            title="Hire a licensed architect",
            description="Stamped drawings, remotely.",
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
        first = api_client.get(PAGE_URL).json()
        assert "faqs" not in first["blocks"]
        FAQ.objects.create(scope="landing", question="Fresh?", answer="Yes")
        second = api_client.get(PAGE_URL).json()
        assert [f["question"] for f in second["blocks"]["faqs"]] == ["Fresh?"]

    def test_etag_304(self, api_client):
        response = api_client.get(PAGE_URL)
        etag = response.headers["ETag"]
        assert response.headers["Cache-Control"].startswith("public")
        cached = api_client.get(PAGE_URL, HTTP_IF_NONE_MATCH=etag)
        assert cached.status_code == 304

    def test_etag_changes_after_edit(self, api_client):
        etag_before = api_client.get(PAGE_URL).headers["ETag"]
        FAQ.objects.create(scope="landing", question="New?", answer="Y")
        etag_after = api_client.get(PAGE_URL).headers["ETag"]
        assert etag_before != etag_after


@pytest.mark.django_db
class TestNavFooter:
    def test_nav_grouped_by_menu(self, api_client):
        group = NavGroup.objects.create(menu="services", heading="Consults & reviews")
        NavItem.objects.create(
            group=group, label="1-hr video consult", href="/services/consult", price_hint="$145"
        )
        body = api_client.get("/api/v1/content/nav/").json()
        services = body["menus"]["services"]
        assert services[0]["heading"] == "Consults & reviews"
        assert services[0]["items"][0]["price_hint"] == "$145"

    def test_footer_columns(self, api_client):
        column = FooterColumn.objects.create(heading="Services")
        FooterLink.objects.create(
            column=column, label="CAD drafting", href="/services/cad-drafting"
        )
        body = api_client.get("/api/v1/content/footer/").json()
        assert body["columns"][0]["heading"] == "Services"
        assert body["columns"][0]["links"][0]["label"] == "CAD drafting"

    def test_settings_endpoint(self, api_client):
        assert api_client.get("/api/v1/content/settings/").status_code == 200
