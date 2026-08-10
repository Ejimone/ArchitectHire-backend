from django.contrib import admin

from .models import Order, OrderFile


class OrderFileInline(admin.TabularInline):
    model = OrderFile
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "customer_email", "total", "status", "expert", "created_at"]
    list_filter = ["kind", "status"]
    search_fields = ["customer_email", "customer_name"]
    readonly_fields = ["subtotal", "stamp_amount", "rush_amount", "total", "config"]
    inlines = [OrderFileInline]
    date_hierarchy = "created_at"
