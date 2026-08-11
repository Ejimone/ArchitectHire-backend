"""Order model strings, calculator guard rails and the signed-in order list."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.orders.calculators import drafting_quote, render_quote
from apps.orders.models import Order, OrderFile


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "catalog")


def test_order_str():
    order = Order(kind="render", customer_email="dana@example.com", total=Decimal("420.00"))
    assert str(order) == "3D visualization · dana@example.com · $420.00"


def test_order_file_str_prefers_the_original_name():
    assert str(OrderFile(original_name="plans.pdf", file="orders/reference/x.pdf")) == "plans.pdf"
    assert str(OrderFile(file="orders/reference/x.pdf")) == "orders/reference/x.pdf"


@pytest.mark.django_db
class TestCalculatorGuards:
    def test_unknown_render_tier(self, seeded):
        with pytest.raises(ValueError, match="Unknown tier"):
            render_quote(deliverable="Interior still", tier="Ultra", qty=1, rush=False)

    def test_render_quantity_bounds(self, seeded):
        with pytest.raises(ValueError, match="Quantity must be 1–10"):
            render_quote(deliverable="Interior still", tier="Conceptual", qty=99, rush=False)

    def test_unknown_drafting_service(self, seeded):
        with pytest.raises(ValueError, match="Unknown service"):
            drafting_quote(service="origami", size=4, stamp=False, rush=False)

    def test_drafting_hours_bounds(self, seeded):
        with pytest.raises(ValueError, match="Hours must be 2–40"):
            drafting_quote(service="cad_drafting", size=1, stamp=False, rush=False)

    def test_pdf_to_cad_sheet_bounds(self, seeded):
        with pytest.raises(ValueError, match="Sheets must be 1–40"):
            drafting_quote(service="pdf_to_cad", size=99, stamp=False, rush=False)


@pytest.mark.django_db
class TestQuoteSerializerGuards:
    @pytest.mark.parametrize("kind", ["render", "drafting"])
    def test_the_matching_config_block_is_required(self, seeded, api_client, kind):
        response = api_client.post("/api/v1/orders/quote/", {"kind": kind}, format="json")
        assert response.status_code == 400
        assert kind in response.json()


@pytest.mark.django_db
class TestMyOrders:
    def test_signed_in_users_see_only_their_own_orders(self, seeded, api_client):
        owner = UserFactory()
        mine = Order.objects.create(
            user=owner,
            kind="render",
            config={},
            customer_email=owner.email,
            subtotal=Decimal("420.00"),
            total=Decimal("420.00"),
        )
        Order.objects.create(
            kind="render",
            config={},
            customer_email="someone-else@example.com",
            subtotal=Decimal("99.00"),
            total=Decimal("99.00"),
        )
        api_client.force_authenticate(user=owner)
        body = api_client.get("/api/v1/orders/mine/").json()
        assert [row["id"] for row in body["results"]] == [str(mine.pk)]
