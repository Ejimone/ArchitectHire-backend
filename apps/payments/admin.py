from django.contrib import admin

from .models import (
    EscrowTransaction,
    FeePolicy,
    PaymentRecord,
    Payout,
    PayoutAccount,
    WebhookEvent,
)


@admin.register(FeePolicy)
class FeePolicyAdmin(admin.ModelAdmin):
    list_display = ["percent", "is_active", "note", "created_at"]
    list_editable = ["is_active"]


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ["kind", "amount", "status", "engagement", "order", "gateway_ref", "created_at"]
    list_filter = ["kind", "status"]
    search_fields = ["gateway_ref"]
    readonly_fields = [f.name for f in PaymentRecord._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(EscrowTransaction)
class EscrowTransactionAdmin(admin.ModelAdmin):
    list_display = ["created_at", "engagement", "account", "entry_type", "amount", "memo"]
    list_filter = ["account", "entry_type"]
    readonly_fields = [f.name for f in EscrowTransaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # append-only ledger


@admin.register(PayoutAccount)
class PayoutAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "bank_label", "status", "gateway_account_id"]
    list_filter = ["status"]


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["provider", "title", "amount", "status", "paid_at"]
    list_filter = ["status"]
    date_hierarchy = "created_at"


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["gateway_id", "event_type", "processed_at", "created_at"]
    search_fields = ["gateway_id", "event_type"]
    readonly_fields = ["gateway_id", "event_type", "payload", "processed_at"]

    def has_add_permission(self, request):
        return False
