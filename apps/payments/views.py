from decimal import Decimal, InvalidOperation

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.engagements.models import Engagement, Milestone

from .models import (
    PaymentRecord,
    PayoutAccount,
    Subscription,
    SubscriptionPlan,
    WebhookEvent,
)
from .services import confirm_payment, ensure_payout_account, escrow_summary, fund_engagement


def _my_engagement(user, pk):
    return get_object_or_404(Engagement.objects.filter(Q(client=user) | Q(provider=user)), pk=pk)


class FundEngagementView(APIView):
    """POST /api/v1/payments/engagements/{id}/fund/ — client funds escrow.
    Optional {"amount": "..."} tops up beyond the default deposit."""

    def post(self, request, pk):
        engagement = _my_engagement(request.user, pk)
        if request.user != engagement.client:
            return Response(
                {"detail": "Only the client funds escrow."}, status=status.HTTP_403_FORBIDDEN
            )
        amount = None
        if request.data.get("amount"):
            try:
                amount = Decimal(str(request.data["amount"]))
            except InvalidOperation:
                return Response({"detail": "Bad amount."}, status=status.HTTP_400_BAD_REQUEST)
            if amount <= 0:
                return Response({"detail": "Bad amount."}, status=status.HTTP_400_BAD_REQUEST)
        record = fund_engagement(engagement, amount=amount, payer=request.user)
        return Response(
            {
                "payment_id": record.pk,
                "gateway_ref": record.gateway_ref,
                "client_secret": record.client_secret,
                "amount": str(record.amount),
                "status": record.status,
            },
            status=status.HTTP_201_CREATED,
        )


class LedgerView(APIView):
    """GET /api/v1/payments/engagements/{id}/ledger/ — balances (both parties)."""

    def get(self, request, pk):
        engagement = _my_engagement(request.user, pk)
        return Response(
            {
                "engagement": engagement.pk,
                "fee_percent": str(engagement.fee_percent),
                "deposit_amount": str(engagement.deposit_amount),
                **escrow_summary(engagement),
            }
        )


class PayoutAccountView(APIView):
    """GET: my payout account. POST: create + get onboarding link."""

    def get(self, request):
        account = PayoutAccount.objects.filter(user=request.user).first()
        if account is None:
            return Response({"status": "none"})
        return Response(
            {
                "status": account.status,
                "bank_label": account.bank_label,
                "gateway_account_id": account.gateway_account_id,
            }
        )

    def post(self, request):
        account, link = ensure_payout_account(request.user)
        return Response(
            {"status": account.status, "bank_label": account.bank_label, "onboarding_url": link}
        )


class EarningsView(APIView):
    """GET /api/v1/payments/earnings/ — provider dashboard numbers.

    Design ("Billing & performance"): the platform never holds a provider's
    money, so these are *booked* figures taken from approved milestones on the
    provider's engagements, alongside their subscription state.
    """

    def get(self, request):
        milestones = Milestone.objects.filter(
            engagement__provider=request.user, paid_at__isnull=False
        ).select_related("engagement")
        now = timezone.now()
        month = milestones.filter(paid_at__year=now.year, paid_at__month=now.month).aggregate(
            s=Sum("amount")
        )["s"] or Decimal("0")
        year = milestones.filter(paid_at__year=now.year).aggregate(s=Sum("amount"))["s"] or Decimal(
            "0"
        )
        in_progress = Milestone.objects.filter(
            engagement__provider=request.user, paid_at__isnull=True
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

        recent = [
            {
                "title": m.title,
                "amount": str(m.amount or Decimal("0")),
                "status": "paid" if m.paid_at else "in_progress",
                "paid_at": m.paid_at,
                "created_at": m.created_at,
            }
            for m in milestones.order_by("-paid_at")[:10]
        ]

        subscription = (
            Subscription.objects.filter(provider=request.user).select_related("plan").first()
        )
        return Response(
            {
                "booked_this_month": str(month),
                "booked_this_year": str(year),
                "in_progress": str(in_progress),
                "recent_contracts": recent,
                "subscription": (
                    {
                        "plan": subscription.plan.name,
                        "price": str(subscription.amount_due),
                        "billing_period": subscription.billing_period,
                        "status": subscription.status,
                        "renews_at": subscription.current_period_end,
                        "card_label": subscription.card_label,
                    }
                    if subscription
                    else None
                ),
            }
        )


class StripeWebhookView(APIView):
    """POST /api/webhooks/stripe/ — signature-verified, deduped."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        from .gateway import get_gateway

        signature = request.headers.get("Stripe-Signature", "")
        try:
            event = get_gateway().verify_webhook(request.body, signature)
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event_id = event.get("id", "")
        if not event_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        record, created = WebhookEvent.objects.get_or_create(
            gateway_id=event_id,
            defaults={"event_type": event.get("type", ""), "payload": event},
        )
        if not created and record.processed_at:
            return Response(status=status.HTTP_200_OK)  # duplicate — already handled

        if event.get("type") == "payment_intent.succeeded":
            intent = event.get("data", {}).get("object", {})
            ref = intent.get("id")
            if ref and PaymentRecord.objects.filter(gateway_ref=ref).exists():
                confirm_payment(ref)
        elif event.get("type") == "account.updated":
            account_data = event.get("data", {}).get("object", {})
            if account_data.get("payouts_enabled"):
                PayoutAccount.objects.filter(gateway_account_id=account_data.get("id", "")).update(
                    status=PayoutAccount.Status.VERIFIED
                )
        elif event.get("type", "").startswith("customer.subscription."):
            data = event.get("data", {}).get("object", {})
            subscription = Subscription.objects.filter(gateway_ref=data.get("id", "")).first()
            if subscription:
                subscription.status = (
                    Subscription.Status.CANCELED
                    if event["type"].endswith("deleted")
                    else data.get("status", subscription.status)
                )
                subscription.save(update_fields=["status"])

        record.processed_at = timezone.now()
        record.save(update_fields=["processed_at"])
        return Response(status=status.HTTP_200_OK)


class PlansView(APIView):
    """GET /api/v1/payments/plans/?group=standard — public subscription tiers."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        group = request.query_params.get("group", SubscriptionPlan.Group.STANDARD)
        plans = SubscriptionPlan.objects.filter(group=group)
        return Response(
            {
                "group": group,
                "plans": [
                    {
                        "key": p.key,
                        "name": p.name,
                        "tagline": p.tagline,
                        "price_monthly": str(p.price_monthly),
                        "price_yearly": str(p.price_yearly) if p.price_yearly is not None else None,
                        "per_unit": p.per_unit,
                        "project_ceiling": p.project_ceiling,
                        "metro_coverage": p.metro_coverage,
                        "pursuit_limit": p.pursuit_limit,
                        "fits": p.fits,
                        "points": p.points,
                        "cta_label": p.cta_label,
                        "is_recommended": p.is_recommended,
                    }
                    for p in plans
                ],
            }
        )


class SubscriptionView(APIView):
    """GET: my subscription. POST {plan, billing_period, seats}: subscribe/switch.
    DELETE: cancel."""

    def get(self, request):
        subscription = (
            Subscription.objects.filter(provider=request.user).select_related("plan").first()
        )
        if subscription is None:
            return Response({"status": "none"})
        return Response(
            {
                "status": subscription.status,
                "plan": subscription.plan.key,
                "plan_name": subscription.plan.name,
                "billing_period": subscription.billing_period,
                "seats": subscription.seats,
                "amount_due": str(subscription.amount_due),
                "renews_at": subscription.current_period_end,
                "card_label": subscription.card_label,
            }
        )

    def post(self, request):
        from .services import subscribe

        plan = SubscriptionPlan.objects.filter(
            key=request.data.get("plan", ""),
            group=request.data.get("group", SubscriptionPlan.Group.STANDARD),
        ).first()
        if plan is None:
            return Response({"detail": "Unknown plan."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            seats = int(request.data.get("seats", 1))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Seats must be a number."}, status=status.HTTP_400_BAD_REQUEST
            )
        if seats < 1:
            return Response(
                {"detail": "Seats must be at least 1."}, status=status.HTTP_400_BAD_REQUEST
            )
        period = request.data.get("billing_period", Subscription.Period.MONTHLY)
        if period not in Subscription.Period.values:
            return Response(
                {"detail": "Unknown billing period."}, status=status.HTTP_400_BAD_REQUEST
            )
        subscription = subscribe(request.user, plan, billing_period=period, seats=seats)
        return Response(
            {
                "status": subscription.status,
                "plan": plan.key,
                "amount_due": str(subscription.amount_due),
            },
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        from .services import cancel_subscription

        subscription = Subscription.objects.filter(provider=request.user).first()
        if subscription is None:
            return Response({"detail": "No subscription."}, status=status.HTTP_404_NOT_FOUND)
        cancel_subscription(subscription)
        return Response({"status": subscription.status})
