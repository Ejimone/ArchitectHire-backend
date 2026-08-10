from django.contrib import admin
from django.utils.html import format_html
from solo.admin import SingletonModelAdmin

from . import admin_editorial  # noqa: F401
from .models import (
    FAQ,
    CopyBlock,
    CredentialBadge,
    FooterColumn,
    FooterLink,
    HeroCarouselSlide,
    MediaAsset,
    NavGroup,
    NavItem,
    PageSEO,
    Persona,
    Principle,
    SiteSettings,
    SocialLink,
    Stat,
    Step,
    Testimonial,
    TrustLogo,
    UseCase,
    ValueProp,
)


@admin.register(SiteSettings)
class SiteSettingsAdmin(SingletonModelAdmin):
    fieldsets = (
        (
            "Promo banner",
            {
                "fields": (
                    "promo_banner_enabled",
                    "promo_banner_text",
                    "promo_banner_cta_label",
                    "promo_banner_cta_href",
                )
            },
        ),
        ("Homepage hero", {"fields": ("hero_media_mode", "hero_image", "hero_video_url")}),
        ("Trust bar", {"fields": ("trust_bar_enabled",)}),
        (
            "Contact emails",
            {"fields": ("contact_email_clients", "contact_email_support", "contact_email_privacy")},
        ),
    )


class ScopedBlockAdmin(admin.ModelAdmin):
    list_filter = ["scope", "status"]
    list_editable = ["sort_order", "status"]
    ordering = ["scope", "sort_order"]
    actions = ["publish_selected", "unpublish_selected"]

    @admin.action(description="Publish selected")
    def publish_selected(self, request, queryset):
        for obj in queryset:
            obj.publish()

    @admin.action(description="Move to draft")
    def unpublish_selected(self, request, queryset):
        queryset.update(status="draft")


@admin.register(FAQ)
class FAQAdmin(ScopedBlockAdmin):
    list_display = ["question", "scope", "sort_order", "status"]
    search_fields = ["question", "answer"]


@admin.register(Stat)
class StatAdmin(ScopedBlockAdmin):
    list_display = ["value", "label", "scope", "sort_order", "status"]
    search_fields = ["value", "label"]


@admin.register(Step)
class StepAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "sort_order", "status"]
    search_fields = ["title"]


@admin.register(Testimonial)
class TestimonialAdmin(ScopedBlockAdmin):
    list_display = ["name", "role", "audience", "scope", "sort_order", "status"]
    list_filter = ["scope", "status", "audience"]
    search_fields = ["name", "quote"]


@admin.register(ValueProp)
class ValuePropAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "sort_order", "status"]
    search_fields = ["title"]


@admin.register(TrustLogo)
class TrustLogoAdmin(ScopedBlockAdmin):
    list_display = ["name", "scope", "sort_order", "status"]


@admin.register(CredentialBadge)
class CredentialBadgeAdmin(ScopedBlockAdmin):
    list_display = ["label", "scope", "sort_order", "status"]


@admin.register(UseCase)
class UseCaseAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "sort_order", "status"]
    search_fields = ["title"]


@admin.register(Persona)
class PersonaAdmin(ScopedBlockAdmin):
    list_display = ["kicker", "title", "scope", "sort_order", "status"]


@admin.register(Principle)
class PrincipleAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "sort_order", "status"]


@admin.register(HeroCarouselSlide)
class HeroCarouselSlideAdmin(ScopedBlockAdmin):
    list_display = ["__str__", "scope", "sort_order", "status", "thumbnail"]

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:40px;border-radius:4px" />', obj.image.url
            )
        return "—"


class NavItemInline(admin.TabularInline):
    model = NavItem
    extra = 0
    fields = ["label", "sublabel", "href", "price_hint", "is_featured", "image", "sort_order"]


@admin.register(NavGroup)
class NavGroupAdmin(admin.ModelAdmin):
    list_display = ["heading", "menu", "sort_order"]
    list_filter = ["menu"]
    list_editable = ["sort_order"]
    inlines = [NavItemInline]


class FooterLinkInline(admin.TabularInline):
    model = FooterLink
    extra = 0
    fields = ["label", "href", "sort_order"]


@admin.register(FooterColumn)
class FooterColumnAdmin(admin.ModelAdmin):
    list_display = ["heading", "sort_order"]
    list_editable = ["sort_order"]
    inlines = [FooterLinkInline]


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display = ["platform", "url", "sort_order"]
    list_editable = ["sort_order"]


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ["slot_key", "thumbnail", "alt_text", "notes"]
    search_fields = ["slot_key", "alt_text", "notes"]

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:40px;border-radius:4px" />', obj.image.url
            )
        return "—"


@admin.register(PageSEO)
class PageSEOAdmin(admin.ModelAdmin):
    list_display = ["page_key", "title"]
    search_fields = ["page_key", "title"]


@admin.register(CopyBlock)
class CopyBlockAdmin(admin.ModelAdmin):
    list_display = ["scope", "key", "short_text", "href"]
    list_filter = ["scope"]
    search_fields = ["scope", "key", "text"]
    ordering = ["scope", "key"]

    @admin.display(description="Text")
    def short_text(self, obj):
        return (obj.text[:80] + "…") if len(obj.text) > 80 else obj.text
