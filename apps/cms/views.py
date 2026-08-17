"""Public content API. Aggressively cached; invalidated by version bump on any CMS save.

The composed page endpoint returns everything a marketing page needs in one JSON:
SEO + site settings + every published scoped block for that page, ordered.
"""

from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.cache import CONTENT_TTL, content_etag, get_content_version, page_cache_key
from apps.core.scopes import is_valid_scope

# Re-exported: `BLOCK_REGISTRY` moved to `compose` when the Studio needed it without
# dragging the view layer along, but `apps.cms.views` is still its established import
# site (studio views, the seed command, the tag tests).
from .compose import BLOCK_REGISTRY, compose_page  # noqa: F401
from .models import (
    CopyBlock,
    FooterColumn,
    MediaAsset,
    NavGroup,
    SiteSettings,
    SocialLink,
)
from .serializers import (
    FooterColumnSerializer,
    MediaAssetSerializer,
    NavGroupSerializer,
    SiteSettingsSerializer,
    SocialLinkSerializer,
)

# No shared-cache lifetime, deliberately. App Platform is fronted by Cloudflare, which
# honoured the old `s-maxage=300` — so a content save purged the frontend's tag, the
# frontend re-fetched, and Cloudflare served it a copy up to five minutes old. The purge
# has no way to reach that cache, which made instant sync unachievable in production
# however fast everything else was.
#
# Next owns content caching now: it holds the payload in its own tagged data cache and
# is told exactly what to drop, so the origin is hit once per purge rather than per
# visitor. The ETag below still makes the revalidation itself cheap.
PUBLIC_CACHE_CONTROL = "public, no-cache, must-revalidate"


class CachedContentView(APIView):
    """Base for public content endpoints: ETag/304 handling + payload caching."""

    authentication_classes = []
    permission_classes = [AllowAny]
    cache_slug = None  # override

    def get(self, request, *args, **kwargs):
        slug = self.get_cache_slug(**kwargs)
        # `(epoch, slug version)`. The slug half is what makes an edit to one page leave
        # every other page's payload warm.
        #
        # The *version* slug is usually the same as the cache slug, but a view whose
        # payload varies by query parameter needs them apart: it must key one cache entry
        # per variant while sharing a single counter, because a tag can only name a
        # counter it knows in advance — not one per arbitrary `?prefix=` a caller invents.
        version = get_content_version(self.get_version_slug(**kwargs))
        payload = cache.get(page_cache_key(slug, version))
        if payload is None:
            payload = self.build_payload(request, **kwargs)
            if payload is None:
                return Response(status=status.HTTP_404_NOT_FOUND)
            # Only keep the payload if nothing bumped the version while we were
            # building it. A bump in that window means a write may have committed
            # after our snapshot was read, and storing it would serve the pre-write
            # page for the full TTL. Serving it once is fine; keeping it is not.
            if get_content_version(self.get_version_slug(**kwargs)) == version:
                cache.set(page_cache_key(slug, version), payload, CONTENT_TTL)

        # Stamped with the version this body was built at, not with whatever the version
        # has since become. Re-reading here would let a write that landed mid-request
        # label the pre-write body with the post-write ETag, and the client would then
        # be told 304 against it until some unrelated write moved the version again.
        etag = content_etag(slug, version)
        if request.headers.get("If-None-Match") == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = Response(payload)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
        return response

    def get_cache_slug(self, **kwargs):
        return self.cache_slug

    def get_version_slug(self, **kwargs):
        """The slug whose counter versions this payload. Override only when one counter
        has to cover several cache keys."""
        return self.get_cache_slug(**kwargs)

    def build_payload(self, request, **kwargs):
        raise NotImplementedError


class PageContentView(CachedContentView):
    """GET /api/v1/content/pages/{page_key}/ — one JSON per marketing page."""

    def get_cache_slug(self, page_key=None):
        return page_key

    def build_payload(self, request, page_key=None):
        if not is_valid_scope(page_key):
            return None
        return compose_page(page_key, request)


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

    #: Ceiling on one response. The inventory is ~170 slots today and grows with every
    #: city and project type, so this is a real bound, not a formality — `truncated` in
    #: the payload tells the caller when it bit rather than letting the tail vanish.
    PAGE_SIZE = 500

    def get_cache_slug(self, **kwargs):
        prefix = self.request.query_params.get("prefix", "")
        return f"_media:{prefix}"

    def get_version_slug(self, **kwargs):
        # One counter for every prefix: a save cannot know which `?prefix=` values
        # callers have cached, and `cms:media` is the tag that moves this counter.
        return "_media"

    def build_payload(self, request):
        queryset = MediaAsset.objects.exclude(image="")
        prefix = request.query_params.get("prefix")
        if prefix:
            queryset = queryset.filter(slot_key__startswith=prefix)
        # Explicit ordering: MediaAsset has no Meta.ordering, so without this *which*
        # rows survive the slice is whatever the planner happens to return.
        assets = list(queryset.order_by("slot_key")[: self.PAGE_SIZE + 1])
        truncated = len(assets) > self.PAGE_SIZE
        return {
            "slots": {
                asset.slot_key: MediaAssetSerializer(asset, context={"request": request}).data
                for asset in assets[: self.PAGE_SIZE]
            },
            "truncated": truncated,
        }
