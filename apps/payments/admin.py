from django.contrib import admin
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter

from apps.studio.admin_base import StudioModelAdmin
from apps.studio.display import PAYMENT_LABELS, status_display

from .models import (
    EscrowTransaction,
    FeePolicy,
    PaymentRecord,
    Payout,
    PayoutAccount,
    Subscription,
    SubscriptionInvoice,
    SubscriptionPlan,
    WebhookEvent,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(StudioModelAdmin):
    """The platform's revenue model, and the source of the public pricing page.

    `gateway_price_id` is the Stripe price the checkout actually charges — DEPLOY.md
    tells the owner to set it here, so it belongs on the changelist where a missing
    value is visible rather than buried in the form.
    """

    list_display = [
        "name",
        "group",
        "key",
        "price_monthly",
        "price_yearly",
        "is_recommended",
        "gateway_price_id",
        "sort_order",
    ]
    list_editable = ["price_monthly", "price_yearly", "is_recommended", "sort_order"]
    list_filter = ["group", "is_recommended"]
    search_fields = ["name", "key", "gateway_price_id"]
    ordering = ["group", "sort_order"]
    fieldsets = (
        (None, {"fields": ("group", "key", "name", "tagline", "sort_order")}),
        ("Pricing", {"fields": ("price_monthly", "price_yearly", "per_unit")}),
        (
            "Positioning",
            {"fields": ("project_ceiling", "metro_coverage", "pursuit_limit", "fits", "points")},
        ),
        ("Call to action", {"fields": ("cta_label", "is_recommended")}),
        ("Stripe", {"fields": ("gateway_price_id",)}),
    )


@admin.register(Subscription)
class SubscriptionAdmin(StudioModelAdmin):
    list_display = [
        "provider",
        "plan",
        "status_pill",
        "billing_period",
        "seats",
        "current_period_end",
    ]
    list_filter = [
        ("status", ChoicesDropdownFilter),
        ("billing_period", ChoicesDropdownFilter),
        ("plan", RelatedDropdownFilter),
    ]

    status_pill = status_display("status", PAYMENT_LABELS)
    search_fields = ["provider__email", "gateway_ref"]
    autocomplete_fields = ["provider", "plan"]


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(StudioModelAdmin):
    list_display = [
        "subscription",
        "amount",
        "status_pill",
        "period_start",
        "period_end",
        "created_at",
    ]
    list_filter = [("status", ChoicesDropdownFilter)]

    status_pill = status_display("status", PAYMENT_LABELS)
    search_fields = ["subscription__provider__email", "gateway_ref"]
    autocomplete_fields = ["subscription"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


@admin.register(FeePolicy)
class FeePolicyAdmin(StudioModelAdmin):
    list_display = ["percent", "is_active", "note", "created_at"]
    list_editable = ["is_active"]


@admin.register(PaymentRecord)
class PaymentRecordAdmin(StudioModelAdmin):
    list_display = [
        "kind",
        "amount",
        "status_pill",
        "engagement",
        "order",
        "gateway_ref",
        "created_at",
    ]
    list_filter = [("kind", ChoicesDropdownFilter), ("status", ChoicesDropdownFilter)]
    date_hierarchy = "created_at"

    status_pill = status_display("status", PAYMENT_LABELS)
    search_fields = ["gateway_ref"]
    readonly_fields = [f.name for f in PaymentRecord._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(EscrowTransaction)
class EscrowTransactionAdmin(StudioModelAdmin):
    list_display = ["created_at", "engagement", "account", "entry_type", "amount", "memo"]
    list_filter = ["account", "entry_type"]
    readonly_fields = [f.name for f in EscrowTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # append-only ledger


@admin.register(PayoutAccount)
class PayoutAccountAdmin(StudioModelAdmin):
    list_display = ["user", "bank_label", "status_pill", "gateway_account_id"]
    list_filter = [("status", ChoicesDropdownFilter)]
    search_fields = ["user__email", "gateway_account_id"]

    status_pill = status_display("status", PAYMENT_LABELS)


@admin.register(Payout)
class PayoutAdmin(StudioModelAdmin):
    list_display = ["provider", "title", "amount", "status_pill", "paid_at"]
    list_filter = [("status", ChoicesDropdownFilter)]
    search_fields = ["provider__email", "title"]

    status_pill = status_display("status", PAYMENT_LABELS)
    date_hierarchy = "created_at"


@admin.register(WebhookEvent)
class WebhookEventAdmin(StudioModelAdmin):
    list_display = ["gateway_id", "event_type", "processed_at", "created_at"]
    search_fields = ["gateway_id", "event_type"]
    readonly_fields = ["gateway_id", "event_type", "payload", "processed_at"]

    def has_add_permission(self, request):
        return False
