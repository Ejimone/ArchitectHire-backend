"""Gateway abstraction: the abstract contract, the mock, and the Stripe adapter.

The Stripe adapter is driven against a stand-in `stripe` module so the request
shapes we send (cents, metadata, price/quantity) are asserted without network.
"""

import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.payments.gateway import BaseGateway, MockGateway, StripeGateway, get_gateway


class TestBaseGatewayContract:
    """Every gateway method is abstract on the base class."""

    def test_all_methods_raise_not_implemented(self):
        gateway = BaseGateway()
        assert gateway.name == "base"
        with pytest.raises(NotImplementedError):
            gateway.create_payment_intent(amount=Decimal("1"), currency="usd", metadata={})
        with pytest.raises(NotImplementedError):
            gateway.create_transfer(amount=Decimal("1"), destination="acct_1", metadata={})
        with pytest.raises(NotImplementedError):
            gateway.create_connect_account(email="a@example.com")
        with pytest.raises(NotImplementedError):
            gateway.create_account_link(account_id="acct_1", refresh_url="/r", return_url="/d")
        with pytest.raises(NotImplementedError):
            gateway.verify_webhook(b"{}", "sig")
        with pytest.raises(NotImplementedError):
            gateway.create_subscription(customer_email="a@example.com", price_id="price", seats=1)
        with pytest.raises(NotImplementedError):
            gateway.cancel_subscription(subscription_ref="sub_1")


class TestMockGateway:
    def test_transfer_account_and_link(self):
        gateway = MockGateway()
        transfer = gateway.create_transfer(
            amount=Decimal("100"), destination="acct_mock", metadata={}
        )
        assert transfer["status"] == "paid"
        assert transfer["id"].startswith("tr_mock_")

        account = gateway.create_connect_account(email="pro@example.com")
        assert account["status"] == "verified"
        assert account["id"].startswith("acct_mock_")

        assert (
            gateway.create_account_link(
                account_id=account["id"], refresh_url="/refresh", return_url="/done"
            )
            == "/done"
        )


@pytest.fixture
def stripe_module(settings):
    """Install a stand-in `stripe` module and configure Stripe credentials."""
    settings.STRIPE_SECRET_KEY = "sk_test_gateway"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_gateway"
    module = MagicMock(name="stripe")
    with patch.dict(sys.modules, {"stripe": module}):
        yield module


class TestStripeGateway:
    def test_get_gateway_selects_stripe_when_configured(self, stripe_module):
        gateway = get_gateway()
        assert isinstance(gateway, StripeGateway)
        assert gateway.name == "stripe"
        assert stripe_module.api_key == "sk_test_gateway"

    def test_get_gateway_falls_back_to_mock(self, settings):
        settings.STRIPE_SECRET_KEY = ""
        assert isinstance(get_gateway(), MockGateway)

    def test_create_payment_intent_converts_to_cents(self, stripe_module):
        stripe_module.PaymentIntent.create.return_value = SimpleNamespace(
            id="pi_1", client_secret="pi_1_secret", status="requires_payment_method"
        )
        result = StripeGateway().create_payment_intent(
            amount=Decimal("5350.00"), currency="usd", metadata={"engagement_id": "3"}
        )
        assert result == {
            "id": "pi_1",
            "client_secret": "pi_1_secret",
            "status": "requires_payment_method",
        }
        kwargs = stripe_module.PaymentIntent.create.call_args.kwargs
        assert kwargs["amount"] == 535000
        assert kwargs["metadata"] == {"engagement_id": "3"}

    def test_create_transfer(self, stripe_module):
        stripe_module.Transfer.create.return_value = SimpleNamespace(id="tr_1")
        result = StripeGateway().create_transfer(
            amount=Decimal("2140.00"), destination="acct_1", metadata={"payout_id": "9"}
        )
        assert result == {"id": "tr_1", "status": "paid"}
        assert stripe_module.Transfer.create.call_args.kwargs["amount"] == 214000

    def test_create_connect_account_and_link(self, stripe_module):
        stripe_module.Account.create.return_value = SimpleNamespace(id="acct_1")
        stripe_module.AccountLink.create.return_value = SimpleNamespace(
            url="https://connect.stripe.test/onboard"
        )
        gateway = StripeGateway()
        assert gateway.create_connect_account(email="pro@example.com") == {
            "id": "acct_1",
            "status": "pending",
        }
        link = gateway.create_account_link(
            account_id="acct_1", refresh_url="/refresh", return_url="/done"
        )
        assert link == "https://connect.stripe.test/onboard"
        assert stripe_module.AccountLink.create.call_args.kwargs["type"] == "account_onboarding"

    def test_verify_webhook_uses_the_signing_secret(self, stripe_module):
        stripe_module.Webhook.construct_event.return_value = SimpleNamespace(
            to_dict=lambda: {"id": "evt_1", "type": "payment_intent.succeeded"}
        )
        event = StripeGateway().verify_webhook(b'{"id": "evt_1"}', "t=1,v1=abc")
        assert event == {"id": "evt_1", "type": "payment_intent.succeeded"}
        assert stripe_module.Webhook.construct_event.call_args.args == (
            b'{"id": "evt_1"}',
            "t=1,v1=abc",
            "whsec_test_gateway",
        )

    def test_create_subscription_creates_customer_and_seats(self, stripe_module):
        stripe_module.Customer.create.return_value = SimpleNamespace(id="cus_1")
        stripe_module.Subscription.create.return_value = SimpleNamespace(
            id="sub_1", status="incomplete", current_period_end=1767225600
        )
        result = StripeGateway().create_subscription(
            customer_email="pro@example.com", price_id="price_practice", seats=3
        )
        assert result == {
            "id": "sub_1",
            "status": "incomplete",
            "current_period_end": 1767225600,
            "card_label": "",
        }
        kwargs = stripe_module.Subscription.create.call_args.kwargs
        assert kwargs["customer"] == "cus_1"
        assert kwargs["items"] == [{"price": "price_practice", "quantity": 3}]

    def test_cancel_subscription(self, stripe_module):
        stripe_module.Subscription.delete.return_value = SimpleNamespace(
            id="sub_1", status="canceled"
        )
        assert StripeGateway().cancel_subscription(subscription_ref="sub_1") == {
            "id": "sub_1",
            "status": "canceled",
        }
