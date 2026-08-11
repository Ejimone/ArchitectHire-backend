from django.urls import path

from .views import (
    EarningsView,
    FundEngagementView,
    LedgerView,
    PayoutAccountView,
    PlansView,
    SubscriptionView,
)

app_name = "payments"

urlpatterns = [
    path("plans/", PlansView.as_view(), name="plans"),
    path("subscription/", SubscriptionView.as_view(), name="subscription"),
    path("engagements/<int:pk>/fund/", FundEngagementView.as_view(), name="fund"),
    path("engagements/<int:pk>/ledger/", LedgerView.as_view(), name="ledger"),
    path("payout-account/", PayoutAccountView.as_view(), name="payout-account"),
    path("earnings/", EarningsView.as_view(), name="earnings"),
]
