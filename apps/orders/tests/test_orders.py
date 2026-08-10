"""Exact-value tests for order calculators (design price matrices)."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.orders.calculators import drafting_quote, render_quote


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "catalog")


@pytest.mark.django_db
class TestRenderCalculator:
    def test_interior_professional_x2(self, seeded):
        quote = render_quote(deliverable="Interior still", tier="Professional", qty=2, rush=False)
        assert quote.total == Decimal("800")

    def test_rush_adds_25pct(self, seeded):
        quote = render_quote(deliverable="Interior still", tier="Professional", qty=2, rush=True)
        assert quote.rush_amount == Decimal("200.00")
        assert quote.total == Decimal("1000.00")

    def test_full_matrix_corners(self, seeded):
        assert render_quote(
            deliverable="3D floor plan", tier="Conceptual", qty=1, rush=False
        ).total == Decimal("100")
        assert render_quote(
            deliverable="360° / VR tour", tier="Photoreal", qty=1, rush=False
        ).total == Decimal("2400")

    def test_unknown_deliverable(self, seeded):
        with pytest.raises(ValueError):
            render_quote(deliverable="Hologram", tier="Conceptual", qty=1, rush=False)


@pytest.mark.django_db
class TestDraftingCalculator:
    def test_hourly(self, seeded):
        quote = drafting_quote(service="cad_drafting", size=8, stamp=False, rush=False)
        assert quote.total == Decimal("624")  # 8 × $78

    def test_asbuilt_minimum_binds(self, seeded):
        quote = drafting_quote(service="asbuilt", size=1500, stamp=False, rush=False)
        assert quote.total == Decimal("2500")  # max($2500, 1500×0.25 rounded)

    def test_pdf_to_cad(self, seeded):
        quote = drafting_quote(service="pdf_to_cad", size=6, stamp=False, rush=False)
        assert quote.total == Decimal("180")  # 6 × $30

    def test_stamp_and_rush(self, seeded):
        quote = drafting_quote(service="cad_drafting", size=8, stamp=True, rush=True)
        # base 624 + stamp 1500 = 2124; rush 25% = 531; total 2655
        assert quote.stamp_amount == Decimal("1500")
        assert quote.rush_amount == Decimal("531.00")
        assert quote.total == Decimal("2655.00")


@pytest.mark.django_db
class TestOrderAPI:
    def test_quote_endpoint_anonymous(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/orders/quote/",
            {
                "kind": "render",
                "render": {
                    "deliverable": "Exterior still",
                    "tier": "Photoreal",
                    "qty": 1,
                    "rush": False,
                },
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["total"] == "2000.00"

    def test_place_order_anonymous(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/orders/",
            {
                "kind": "drafting",
                "drafting": {"service": "asbuilt", "size": 1500, "stamp": True, "rush": False},
                "customer_email": "homeowner@example.com",
                "customer_name": "Dana",
                "have": "PDFs / scans",
                "notes": "Two-story craftsman",
            },
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending_payment"
        assert body["total"] == "4000.00"  # 2500 + 1500 stamp
        assert body["config"]["have"] == "PDFs / scans"

        detail = api_client.get(f"/api/v1/orders/{body['id']}/")
        assert detail.status_code == 200

    def test_invalid_config_rejected(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/orders/quote/",
            {"kind": "drafting", "drafting": {"service": "asbuilt", "size": 99, "stamp": False}},
            format="json",
        )
        assert response.status_code == 400
