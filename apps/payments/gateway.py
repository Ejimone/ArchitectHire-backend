"""Payment gateway abstraction — Stripe in real environments, deterministic mock
when no keys are configured (local dev, CI). Models store gateway-neutral refs
so the provider is swappable.
"""

import uuid
from decimal import Decimal

from django.conf import settings


class BaseGateway:
    name = "base"

    def create_payment_intent(self, *, amount: Decimal, currency: str, metadata: dict) -> dict:
        raise NotImplementedError

    def create_transfer(self, *, amount: Decimal, destination: str, metadata: dict) -> dict:
        raise NotImplementedError

    def create_connect_account(self, *, email: str) -> dict:
        raise NotImplementedError

    def create_account_link(self, *, account_id: str, refresh_url: str, return_url: str) -> str:
        raise NotImplementedError

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        raise NotImplementedError

    def create_subscription(self, *, customer_email: str, price_id: str, seats: int) -> dict:
        raise NotImplementedError

    def cancel_subscription(self, *, subscription_ref: str) -> dict:
        raise NotImplementedError


class MockGateway(BaseGateway):
    """Deterministic in-memory gateway: intents succeed instantly, accounts verify
    instantly. Lets the whole escrow flow run end-to-end without Stripe keys."""

    name = "mock"

    def create_payment_intent(self, *, amount, currency, metadata):
        ref = f"pi_mock_{uuid.uuid4().hex[:20]}"
        return {"id": ref, "client_secret": f"{ref}_secret", "status": "succeeded"}

    def create_transfer(self, *, amount, destination, metadata):
        return {"id": f"tr_mock_{uuid.uuid4().hex[:20]}", "status": "paid"}

    def create_connect_account(self, *, email):
        return {"id": f"acct_mock_{uuid.uuid4().hex[:16]}", "status": "verified"}

    def create_account_link(self, *, account_id, refresh_url, return_url):
        return return_url  # nothing to onboard in mock mode

    def verify_webhook(self, payload, signature):
        import json

        return json.loads(payload)

    def create_subscription(self, *, customer_email, price_id, seats):
        return {
            "id": f"sub_mock_{uuid.uuid4().hex[:20]}",
            "status": "active",
            "current_period_end": None,
            "card_label": "Mock Card ••4242",
        }

    def cancel_subscription(self, *, subscription_ref):
        return {"id": subscription_ref, "status": "canceled"}


class StripeGateway(BaseGateway):
    name = "stripe"

    def __init__(self):
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        self.stripe = stripe

    @staticmethod
    def _cents(amount: Decimal) -> int:
        return int((amount * 100).quantize(Decimal("1")))

    def create_payment_intent(self, *, amount, currency, metadata):
        intent = self.stripe.PaymentIntent.create(
            amount=self._cents(amount),
            currency=currency,
            metadata=metadata,
            automatic_payment_methods={"enabled": True},
        )
        return {"id": intent.id, "client_secret": intent.client_secret, "status": intent.status}

    def create_transfer(self, *, amount, destination, metadata):
        transfer = self.stripe.Transfer.create(
            amount=self._cents(amount), currency="usd", destination=destination, metadata=metadata
        )
        return {"id": transfer.id, "status": "paid"}

    def create_connect_account(self, *, email):
        account = self.stripe.Account.create(type="express", email=email)
        return {"id": account.id, "status": "pending"}

    def create_account_link(self, *, account_id, refresh_url, return_url):
        link = self.stripe.AccountLink.create(
            account=account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )
        return link.url

    def verify_webhook(self, payload, signature):
        event = self.stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
        return event.to_dict()

    def create_subscription(self, *, customer_email, price_id, seats):
        customer = self.stripe.Customer.create(email=customer_email)
        subscription = self.stripe.Subscription.create(
            customer=customer.id,
            items=[{"price": price_id, "quantity": seats}],
            payment_behavior="default_incomplete",
        )
        return {
            "id": subscription.id,
            "status": subscription.status,
            "current_period_end": subscription.current_period_end,
            "card_label": "",
        }

    def cancel_subscription(self, *, subscription_ref):
        subscription = self.stripe.Subscription.delete(subscription_ref)
        return {"id": subscription.id, "status": subscription.status}


def get_gateway() -> BaseGateway:
    if settings.STRIPE_SECRET_KEY:
        return StripeGateway()
    return MockGateway()
