"""Public content API. Aggressively cached; invalidated by version bump on any CMS save.

The composed page endpoint returns everything a marketing page needs in one JSON:
SEO + site settings + every published scoped block for that page, ordered.
"""

from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.cache import CONTENT_TTL, content_etag, page_cache_key
from apps.core.scopes import is_valid_scope

from .models import (
    FAQ,
    CaseCard,
    CopyBlock,
    CredentialBadge,
    EstimateTeaserOption,
    FeatureMatrixRow,
    FooterColumn,
    HeroCarouselSlide,
    MediaAsset,
    NavGroup,
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
from .serializers import (
    CaseCardSerializer,
    CredentialBadgeSerializer,
    EstimateTeaserOptionSerializer,
    FAQSerializer,
    FeatureMatrixRowSerializer,
    FooterColumnSerializer,
    HeroCarouselSlideSerializer,
    MediaAssetSerializer,
    NavGroupSerializer,
    PageSEOSerializer,
    PersonaSerializer,
    PrincipleSerializer,
    SiteSettingsSerializer,
    SocialLinkSerializer,
    StatSerializer,
    StepSerializer,
    TestimonialSerializer,
    TrustLogoSerializer,
    UseCaseSerializer,
    ValuePropSerializer,
)

BLOCK_REGISTRY = [
    ("faqs", FAQ, FAQSerializer),
    ("stats", Stat, StatSerializer),
    ("steps", Step, StepSerializer),
    ("testimonials", Testimonial, TestimonialSerializer),
    ("value_props", ValueProp, ValuePropSerializer),
    ("trust_logos", TrustLogo, TrustLogoSerializer),
    ("credential_badges", CredentialBadge, CredentialBadgeSerializer),
    ("use_cases", UseCase, UseCaseSerializer),
    ("personas", Persona, PersonaSerializer),
    ("principles", Principle, PrincipleSerializer),
    ("carousel", HeroCarouselSlide, HeroCarouselSlideSerializer),
    ("case_cards", CaseCard, CaseCardSerializer),
    ("estimate_teaser", EstimateTeaserOption, EstimateTeaserOptionSerializer),
    ("feature_matrix", FeatureMatrixRow, FeatureMatrixRowSerializer),
]

PUBLIC_CACHE_CONTROL = "public, s-maxage=300, stale-while-revalidate=600"


class CachedContentView(APIView):
    """Base for public content endpoints: ETag/304 handling + payload caching."""

    authentication_classes = []
    permission_classes = [AllowAny]
    cache_slug = None  # override

    def get(self, request, *args, **kwargs):
        slug = self.get_cache_slug(**kwargs)
        payload = cache.get(page_cache_key(slug))
        if payload is None:
            payload = self.build_payload(request, **kwargs)
            if payload is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            # Key is recomputed after the build: a first-time build can create rows
            # (e.g. the SiteSettings singleton) which bump the content version.
            cache.set(page_cache_key(slug), payload, CONTENT_TTL)

        etag = content_etag(slug)
        if request.headers.get("If-None-Match") == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = Response(payload)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
        return response

    def get_cache_slug(self, **kwargs):
        return self.cache_slug

    def build_payload(self, request, **kwargs):
        raise NotImplementedError


class PageContentView(CachedContentView):
    """GET /api/v1/content/pages/{page_key}/ — one JSON per marketing page."""

    def get_cache_slug(self, page_key=None):
        return page_key

    def build_payload(self, request, page_key=None):
        if not is_valid_scope(page_key):
            return None

        settings_obj = SiteSettings.get_solo()
        seo = PageSEO.objects.filter(page_key=page_key).first()

        blocks = {}
        for name, model, serializer_class in BLOCK_REGISTRY:
            queryset = model.objects.published().filter(scope=page_key)
            data = serializer_class(queryset, many=True, context={"request": request}).data
            if data:
                blocks[name] = data

        media = MediaAsset.objects.filter(slot_key__startswith=f"{page_key}:").exclude(image="")
        media_map = {
            asset.slot_key: MediaAssetSerializer(asset, context={"request": request}).data
            for asset in media
        }

        copy = {
            block.key: {"text": block.text, "href": block.href}
            for block in CopyBlock.objects.filter(scope=page_key)
        }

        return {
            "page": page_key,
            "seo": PageSEOSerializer(seo, context={"request": request}).data if seo else None,
            "settings": SiteSettingsSerializer(settings_obj, context={"request": request}).data,
            "copy": copy,
            "blocks": blocks,
            "media": media_map,
        }


def _chrome_copy():
    """Site-shell copy (nav labels, auth buttons, footer legal) — scope 'chrome'."""
    return {
        block.key: {"text": block.text, "href": block.href}
        for block in CopyBlock.objects.filter(scope="chrome")
    }


class NavigationView(CachedContentView):
    """GET /api/v1/content/nav/ — the three mega-dropdowns, grouped."""

    cache_slug = "_nav"

    def build_payload(self, request):
        groups = NavGroup.objects.prefetch_related("items").all()
        menus = {}
        for group in groups:
            menus.setdefault(group.menu, []).append(
                NavGroupSerializer(group, context={"request": request}).data
            )
        return {"menus": menus, "copy": _chrome_copy()}


class FooterView(CachedContentView):
    """GET /api/v1/content/footer/ — columns + social links."""

    cache_slug = "_footer"

    def build_payload(self, request):
        columns = FooterColumn.objects.prefetch_related("links").all()
        return {
            "columns": FooterColumnSerializer(
                columns, many=True, context={"request": request}
            ).data,
            "social": SocialLinkSerializer(SocialLink.objects.all(), many=True).data,
            "copy": _chrome_copy(),
        }


class SettingsView(CachedContentView):
    """GET /api/v1/content/settings/ — global site settings."""

    cache_slug = "_settings"

    def build_payload(self, request):
        return SiteSettingsSerializer(SiteSettings.get_solo(), context={"request": request}).data


class MediaSlotsView(CachedContentView):
    """GET /api/v1/content/media/?prefix=landing — named image slots."""

    def get_cache_slug(self, **kwargs):
        prefix = self.request.query_params.get("prefix", "")
        return f"_media:{prefix}"

    def build_payload(self, request):
        queryset = MediaAsset.objects.exclude(image="")
        prefix = request.query_params.get("prefix")
        if prefix:
            queryset = queryset.filter(slot_key__startswith=prefix)
        return {
            "slots": {
                asset.slot_key: MediaAssetSerializer(asset, context={"request": request}).data
                for asset in queryset[:500]
            }
        }
