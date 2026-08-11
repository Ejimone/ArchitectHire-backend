"""Catalog model strings and the remaining cached catalog endpoints."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.catalog import models as catalog


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog")


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (catalog.ServiceCategory(name="Consults & plan reviews"), "Consults & plan reviews"),
        (catalog.Service(name="CAD drafting"), "CAD drafting"),
        (catalog.Addon(label="Structural", price=Decimal("2400.00")), "Structural ($2400.00)"),
        (catalog.Plan(title="Dynamic fixed quote"), "Dynamic fixed quote"),
        (catalog.ProjectType(name="Backyard ADU"), "Backyard ADU"),
        (catalog.RenderDeliverable(name="Interior still"), "Interior still"),
        (catalog.DraftingConfig(), "Drafting pricing config"),
        (catalog.EstimateConfig(), "Estimate engine config"),
    ],
)
def test_str(obj, expected):
    assert str(obj) == expected


def test_render_deliverable_price_for_each_tier():
    row = catalog.RenderDeliverable(
        name="Interior still",
        conceptual=Decimal("120"),
        professional=Decimal("420"),
        photoreal=Decimal("1200"),
    )
    assert row.price_for("Conceptual") == Decimal("120")
    assert row.price_for("Professional") == Decimal("420")
    assert row.price_for("Photoreal") == Decimal("1200")


@pytest.mark.django_db
class TestCatalogEndpoints:
    def test_addons(self, seeded, api_client):
        keys = [a["key"] for a in api_client.get("/api/v1/catalog/addons/").json()["addons"]]
        assert "structural" in keys

    def test_plans(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/plans/").json()
        assert len(body["plans"]) == 2

    def test_project_types(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/project-types/").json()
        assert any(p["slug"] == "backyard-adu" for p in body["project_types"])

    def test_project_type_detail(self, seeded, api_client):
        body = api_client.get("/api/v1/catalog/project-types/backyard-adu/").json()
        assert body["slug"] == "backyard-adu"

    def test_unknown_project_type_404(self, seeded, api_client):
        assert api_client.get("/api/v1/catalog/project-types/not-a-type/").status_code == 404
