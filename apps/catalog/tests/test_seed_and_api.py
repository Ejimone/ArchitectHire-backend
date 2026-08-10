import pytest
from django.core.management import call_command

from apps.catalog.models import Service
from apps.jurisdictions.models import State


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--all")


@pytest.mark.django_db
class TestSeed:
    def test_counts_match_design(self, seeded):
        from apps.catalog.models import Addon, Plan, ProjectType, RenderDeliverable, ServiceCategory
        from apps.cms.models import FooterColumn, NavGroup, SocialLink
        from apps.jurisdictions.models import City

        assert State.objects.count() == 52
        assert City.objects.count() == 12
        assert ServiceCategory.objects.count() == 8
        assert Service.objects.count() == 27
        assert Addon.objects.count() == 4
        assert Plan.objects.count() == 2
        assert ProjectType.objects.count() == 9
        assert RenderDeliverable.objects.count() == 5
        assert NavGroup.objects.count() == 9
        assert FooterColumn.objects.count() == 5
        assert SocialLink.objects.count() == 4

    def test_idempotent(self, seeded):
        before = Service.objects.count()
        call_command("seed", "--all")
        assert Service.objects.count() == before

    def test_stamp_line(self, seeded):
        assert Service.objects.get(slug="structural-stamp-residential").requires_stamp
        assert not Service.objects.get(slug="cad-drafting").requires_stamp


@pytest.mark.django_db
class TestCatalogAPI:
    def test_categories_with_services(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/categories/").json()
        assert len(body["categories"]) == 8
        consults = body["categories"][0]
        assert consults["name"] == "Consults & plan reviews"
        assert consults["services"][0]["price_display"] == "from $145"

    def test_render_matrix(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/pricing/render-matrix/").json()
        interior = next(d for d in body["deliverables"] if d["name"] == "Interior still")
        assert float(interior["conceptual"]) == 120
        assert float(interior["photoreal"]) == 1200
        assert len(body["quality_tiers"]) == 3

    def test_drafting_pricing(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/pricing/drafting/").json()
        assert float(body["hourly_rate"]) == 78
        assert float(body["stamp_fee"]) == 1500
        assert body["rush_pct"] == 25

    def test_states_endpoint(self, seeded, api_client):
        body = api_client.get("/api/v1/jurisdictions/states/").json()
        assert len(body["states"]) == 52
        ca = next(s for s in body["states"] if s["code"] == "CA")
        assert ca["complexity_score"] == 82
        assert ca["band"] == "HIGH"
        assert ca["multiplier"] == pytest.approx(1.337)

    def test_state_detail_with_factors(self, seeded, api_client):
        body = api_client.get("/api/v1/jurisdictions/states/ca/").json()
        assert body["name"] == "California"
        assert len(body["factors"]) == 5

    def test_nav_seeded(self, seeded, api_client):
        body = api_client.get("/api/v1/content/nav/").json()
        assert len(body["menus"]["services"]) == 7
        projects = body["menus"]["projects"][0]["items"]
        assert projects[0]["label"] == "Backyard ADU"
        assert projects[0]["price_hint"] == "From $2,400"
        assert projects[0]["href"] == "/projects/backyard-adu"
