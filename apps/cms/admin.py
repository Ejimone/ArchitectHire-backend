from django.contrib import admin
from unfold.contrib.filters.admin import AllValuesCheckboxFilter, ChoicesDropdownFilter

from apps.core.cache import bump_content_version
from apps.studio.admin_base import (
    StudioModelAdmin,
    StudioSingletonAdmin,
    StudioTabularInline,
)
from apps.studio.display import status_display, thumbnail_display, truncated_display

from . import admin_editorial  # noqa: F401
from .models import (
    FAQ,
    CaseCard,
    CopyBlock,
    CredentialBadge,
    EstimateTeaserOption,
    FeatureMatrixRow,
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
class SiteSettingsAdmin(StudioSingletonAdmin):
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


class ScopedBlockAdmin(StudioModelAdmin):
    """Shared behaviour for the 14 scoped block types.

    `scope` and `group` are long, high-cardinality lists, so they get searchable
    dropdown filters instead of the default column of links. `ordering_field` turns
    the changelist into a drag-to-reorder list, which is how `sort_order` is actually
    meant to be edited.
    """

    list_filter = [
        ("scope", AllValuesCheckboxFilter),
        ("group", AllValuesCheckboxFilter),
        ("status", ChoicesDropdownFilter),
    ]
    # `status` is deliberately not inline-editable any more: it renders as a colour
    # pill, which scans far better down a long list, and publishing now has three
    # better routes — the bulk actions below, the Publish Queue, and the composer's
    # "Publish page". `sort_order` is appended to list_editable by Unfold at request
    # time to drive drag-reordering, so it stays out of the class attribute.
    list_editable = []
    ordering = ["scope", "group", "sort_order"]
    ordering_field = "sort_order"
    list_filter_submit = True
    actions = ["publish_selected", "unpublish_selected"]

    status_pill = status_display()

    @admin.action(description="Publish selected")
    def publish_selected(self, request, queryset):
        for obj in queryset:
            obj.publish()

    @admin.action(description="Move to draft")
    def unpublish_selected(self, request, queryset):
        # Bulk update rather than per-object save: unpublishing is a single
        # intent, and the post_save cache bump would fire once per row. `update()`
        # emits no signal at all, though, so the pages these rows were on have to be
        # purged by hand — and their scopes read before the rows change under us.
        scopes = set(queryset.values_list("scope", flat=True))
        queryset.update(status="draft")
        bump_content_version({f"cms:page:{scope}" for scope in scopes})


@admin.register(FAQ)
class FAQAdmin(ScopedBlockAdmin):
    list_display = ["question", "scope", "group", "sort_order", "status_pill"]
    search_fields = ["question", "answer"]


@admin.register(Stat)
class StatAdmin(ScopedBlockAdmin):
    list_display = ["value", "label", "scope", "group", "sort_order", "status_pill"]
    search_fields = ["value", "label"]


@admin.register(Step)
class StepAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "group", "sort_order", "status_pill"]
    search_fields = ["title"]


@admin.register(Testimonial)
class TestimonialAdmin(ScopedBlockAdmin):
    list_display = ["name", "role", "audience", "scope", "group", "sort_order", "status_pill"]
    list_filter = [*ScopedBlockAdmin.list_filter, ("audience", ChoicesDropdownFilter)]
    search_fields = ["name", "quote"]


@admin.register(ValueProp)
class ValuePropAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "group", "sort_order", "status_pill"]
    search_fields = ["title"]


@admin.register(TrustLogo)
class TrustLogoAdmin(ScopedBlockAdmin):
    list_display = ["name", "scope", "group", "sort_order", "status_pill"]


@admin.register(CredentialBadge)
class CredentialBadgeAdmin(ScopedBlockAdmin):
    list_display = ["label", "scope", "group", "sort_order", "status_pill"]


@admin.register(UseCase)
class UseCaseAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "group", "sort_order", "status_pill"]
    search_fields = ["title"]


@admin.register(Persona)
class PersonaAdmin(ScopedBlockAdmin):
    list_display = ["kicker", "title", "scope", "group", "sort_order", "status_pill"]


@admin.register(Principle)
class PrincipleAdmin(ScopedBlockAdmin):
    list_display = ["title", "scope", "group", "sort_order", "status_pill"]


@admin.register(CaseCard)
class CaseCardAdmin(ScopedBlockAdmin):
    list_display = [
        "preview",
        "title",
        "category_tag",
        "location",
        "scope",
        "sort_order",
        "status_pill",
    ]
    search_fields = ["title"]

    preview = thumbnail_display()


@admin.register(EstimateTeaserOption)
class EstimateTeaserOptionAdmin(ScopedBlockAdmin):
    list_display = [
        "label",
        "price_range",
        "bar_pct",
        "scope",
        "group",
        "sort_order",
        "status_pill",
    ]


@admin.register(FeatureMatrixRow)
class FeatureMatrixRowAdmin(ScopedBlockAdmin):
    list_display = [
        "label",
        "tier1",
        "tier2",
        "tier3",
        "is_flagship",
        "scope",
        "sort_order",
        "status_pill",
    ]
    search_fields = ["label"]


@admin.register(HeroCarouselSlide)
class HeroCarouselSlideAdmin(ScopedBlockAdmin):
    list_display = ["preview", "__str__", "scope", "group", "sort_order", "status_pill"]

    preview = thumbnail_display()


class NavItemInline(StudioTabularInline):
    model = NavItem
    extra = 0
    fields = ["label", "sublabel", "href", "price_hint", "is_featured", "image", "sort_order"]


@admin.register(NavGroup)
class NavGroupAdmin(StudioModelAdmin):
    list_display = ["heading", "menu", "sort_order"]
    list_filter = ["menu"]
    list_editable = ["sort_order"]
    inlines = [NavItemInline]


class FooterLinkInline(StudioTabularInline):
    model = FooterLink
    extra = 0
    fields = ["label", "href", "sort_order"]


@admin.register(FooterColumn)
class FooterColumnAdmin(StudioModelAdmin):
    list_display = ["heading", "sort_order"]
    list_editable = ["sort_order"]
    inlines = [FooterLinkInline]


@admin.register(SocialLink)
class SocialLinkAdmin(StudioModelAdmin):
    list_display = ["platform", "url", "sort_order"]
    list_editable = ["sort_order"]


@admin.register(MediaAsset)
class MediaAssetAdmin(StudioModelAdmin):
    """Rows are auto-created (one per image slot on the site) — the owner just
    opens a row and uploads. `notes` says where the image appears."""

    list_display = ["preview", "notes", "slot_key", "alt_text", "source"]
    # `credit` is set only on seeded stock, so filtering on it empty/not-empty is the
    # "which slots still need our own photography?" question the owner actually asks.
    list_filter = [("image", admin.EmptyFieldListFilter), ("credit", admin.EmptyFieldListFilter)]
    search_fields = ["slot_key", "alt_text", "notes"]
    fields = ["notes", "slot_key", "image", "alt_text", "credit"]

    @admin.display(description="Source")
    def source(self, obj):
        if not obj.image:
            return "— empty —"
        return obj.credit or "Own photography"

    preview = thumbnail_display()

    def get_readonly_fields(self, request, obj=None):
        """Lock the slot key for ordinary staff; leave `notes` open to everyone.

        Slot keys are system-generated and typing one by hand is how you get a row that
        renders nowhere, so they stay locked in day-to-day use. But locking them
        *permanently* left no way to repair a row whose key was wrong: `sync_media_slots`
        only prunes rows with no image, so a filled row under a stale key was
        unreachable from the site and undeletable from here. Superusers can fix it.

        `notes` is just the human label ("About — hero image") the owner reads to find
        the right row; there is no reason it was ever readonly.
        """
        if obj and not request.user.is_superuser:
            return ["slot_key"]
        return []


@admin.register(PageSEO)
class PageSEOAdmin(StudioModelAdmin):
    list_display = ["page_key", "title", "short_description", "og_preview"]
    search_fields = ["page_key", "title", "description"]
    ordering = ["page_key"]

    short_description = truncated_display("description", 90, description="Description")
    og_preview = thumbnail_display("og_image", description="OG image")


@admin.register(CopyBlock)
class CopyBlockAdmin(StudioModelAdmin):
    """The largest changelist in the project — the seed alone creates ~1,800 rows,
    one per literal string on the site. Filtering by page is the only usable entry
    point, so `scope` gets a multi-select rather than a column of 50 links."""

    list_display = ["scope", "key", "short_text", "href"]
    list_filter = [("scope", AllValuesCheckboxFilter)]
    search_fields = ["scope", "key", "text"]
    ordering = ["scope", "key"]

    short_text = truncated_display("text", 80, description="Text")
