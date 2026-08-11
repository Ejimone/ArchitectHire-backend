from django.contrib import admin

from .models import Message, Thread, ThreadParticipant


class ThreadParticipantInline(admin.TabularInline):
    model = ThreadParticipant
    extra = 0


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ["id", "project", "order", "archived", "updated_at"]
    list_filter = ["archived"]
    inlines = [ThreadParticipantInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["thread", "sender", "kind", "short_body", "created_at"]
    list_filter = ["kind"]
    search_fields = ["body", "sender__email"]

    @admin.display(description="Body")
    def short_body(self, obj):
        return obj.body[:60]
