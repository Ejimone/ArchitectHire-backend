"""Studio's custom admin pages.

Each view is a plain Django class-based view rendered inside the Unfold shell via
`UnfoldSiteViewMixin`, which supplies `admin_site.each_context()` so the sidebar,
header and theme come along for free.

These exist because Django's admin is organised one-model-per-screen, and the three
jobs the owner does most often each span many models at once: assembling a page,
filling image slots, and shipping drafts.
"""

from typing import Any

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from unfold.views import UnfoldSiteViewMixin

from apps.cms.models import CopyBlock, MediaAsset, PageSEO
from apps.cms.slots import sync_media_slots
from apps.cms.views import BLOCK_REGISTRY
from apps.core.scopes import is_valid_scope
from apps.studio import pages as page_registry
from apps.studio.publishing import draft_groups, draft_queryset, publishable_models


class StudioPageView(UnfoldSiteViewMixin, TemplateView):
    """Base for Studio pages: staff-only, rendered in the Unfold shell."""

    permission_required = ()

    def has_permission(self) -> bool:
        user = self.request.user
        return bool(user.is_active and user.is_staff)


# --- Page Composer -----------------------------------------------------------


class PageListView(StudioPageView):
    title = "Pages"
    template_name = "studio/page_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip().lower()

        refs = page_registry.all_pages()
        if query:
            refs = [r for r in refs if query in r.key.lower() or query in r.label.lower()]

        sections: dict[str, list] = {}
        for ref in refs:
            sections.setdefault(ref.section, []).append(ref)

        context.update(
            {
                "query": query,
                "sections": sections,
                "total_pages": len(refs),
            }
        )
        return context


class PageComposerView(StudioPageView):
    """Every piece of content on one page, on one screen.

    Without this, editing the homepage means visiting up to fourteen changelists and
    filtering each by `scope=landing`.
    """

    title = "Page"
    template_name = "studio/page_composer.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        page_key = kwargs.get("page_key", "")
        if not is_valid_scope(page_key):
            raise Http404(f"'{page_key}' is not a valid page key")

        context = super().get_context_data(**kwargs)
        ref = page_registry.find_page(page_key) or page_registry.PageRef(
            key=page_key,
            label=page_registry.humanise(page_key),
            section="Other",
            route=page_registry.route_for(page_key),
        )

        context.update(
            {
                "title": ref.label,
                "page_ref": ref,
                "seo": PageSEO.objects.filter(page_key=page_key).first(),
                "seo_add_url": (f"{reverse('admin:cms_pageseo_add')}?page_key={page_key}"),
                "copy_blocks": CopyBlock.objects.filter(scope=page_key).order_by("key"),
                "block_stacks": self._block_stacks(page_key),
                "media": MediaAsset.objects.filter(slot_key__startswith=f"{page_key}:").order_by(
                    "slot_key"
                ),
                "draft_count": self._draft_count(page_key),
                "preview_url": self._preview_url(ref),
            }
        )
        return context

    def _block_stacks(self, page_key: str) -> list[dict[str, Any]]:
        """One entry per block type that appears on this page.

        Driven by the same BLOCK_REGISTRY the public content endpoint uses, so the
        composer shows exactly what the frontend will receive — no second list to
        keep in sync.
        """
        stacks = []
        for name, model, _serializer in BLOCK_REGISTRY:
            objects = list(
                model._default_manager.filter(scope=page_key).order_by("sort_order", "id")
            )
            if not objects:
                continue
            meta = model._meta
            change_route = f"admin:{meta.app_label}_{meta.model_name}_change"
            stacks.append(
                {
                    "name": name,
                    "label": str(meta.verbose_name_plural).capitalize(),
                    "count": len(objects),
                    "draft_count": sum(1 for obj in objects if obj.status == "draft"),
                    "rows": [
                        {
                            "label": str(obj),
                            "sort_order": obj.sort_order,
                            "group": getattr(obj, "group", ""),
                            "is_published": obj.status == "published",
                            "change_url": reverse(change_route, args=[obj.pk]),
                        }
                        for obj in objects
                    ],
                    "changelist_url": (
                        f"{reverse(f'admin:{meta.app_label}_{meta.model_name}_changelist')}"
                        f"?scope={page_key}"
                    ),
                    "add_url": (
                        f"{reverse(f'admin:{meta.app_label}_{meta.model_name}_add')}"
                        f"?scope={page_key}"
                    ),
                }
            )
        return stacks

    def _draft_count(self, page_key: str) -> int:
        total = 0
        for _name, model, _serializer in BLOCK_REGISTRY:
            total += model._default_manager.filter(scope=page_key, status="draft").count()
        return total

    def _preview_url(self, ref) -> str | None:
        from django.conf import settings

        if not ref.route:
            return None
        return f"{settings.FRONTEND_URL.rstrip('/')}{ref.route}"


# --- Media Library -----------------------------------------------------------


class MediaLibraryView(StudioPageView):
    """The image-slot inventory as a visual grid.

    `MediaAsset` rows are generated by `apps.cms.slots`, one per placeholder on the
    site, so the job is never "find an asset" — it is "see which slots are still
    empty". A changelist cannot show that; a grid of thumbnails can.
    """

    title = "Media library"
    template_name = "studio/media.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        state = self.request.GET.get("state") or "all"
        page_filter = self.request.GET.get("page_key") or ""

        assets = MediaAsset.objects.all()
        if query:
            assets = assets.filter(
                Q(slot_key__icontains=query)
                | Q(notes__icontains=query)
                | Q(alt_text__icontains=query)
            )
        if page_filter:
            assets = assets.filter(slot_key__startswith=f"{page_filter}:")
        if state == "empty":
            assets = assets.filter(image="")
        elif state == "filled":
            assets = assets.exclude(image="")

        assets = assets.order_by("slot_key")

        groups: dict[str, list[MediaAsset]] = {}
        for asset in assets:
            scope = asset.slot_key.rpartition(":")[0] or "other"
            groups.setdefault(scope, []).append(asset)

        total = MediaAsset.objects.count()
        filled = MediaAsset.objects.exclude(image="").count()
        all_keys = MediaAsset.objects.values_list("slot_key", flat=True)
        page_choices = sorted({key.rpartition(":")[0] for key in all_keys})

        context.update(
            {
                "groups": groups,
                "query": query,
                "state": state,
                "page_filter": page_filter,
                "page_choices": page_choices,
                "total_slots": total,
                "filled_slots": filled,
                "empty_slots": total - filled,
                "shown": assets.count(),
                "upload_url": reverse("admin:studio_media_upload"),
                "sync_url": reverse("admin:studio_media_sync"),
            }
        )
        return context


class MediaUploadView(UnfoldSiteViewMixin, TemplateView):
    """Async upload into one slot. Returns JSON so the grid updates in place.

    Access is enforced once, by `PermissionRequiredMixin.dispatch` calling
    `has_permission()` below; the route is additionally wrapped in `admin_view()`,
    which handles the redirect-to-login for anonymous users.
    """

    title = "Upload"
    permission_required = ()

    def has_permission(self) -> bool:
        user = self.request.user
        return bool(user.is_active and user.is_staff and user.has_perm("cms.change_mediaasset"))

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        slot_key = request.POST.get("slot_key", "")
        upload = request.FILES.get("image")
        if not slot_key or not upload:
            return JsonResponse({"error": "slot_key and image are required."}, status=400)

        try:
            asset = MediaAsset.objects.get(slot_key=slot_key)
        except MediaAsset.DoesNotExist:
            return JsonResponse({"error": f"No slot named '{slot_key}'."}, status=404)

        asset.image = upload
        if request.POST.get("alt_text"):
            asset.alt_text = request.POST["alt_text"]
        # save() rather than update(): the post_save signal is what bumps the content
        # cache version and pings the frontend to revalidate.
        asset.save()

        return JsonResponse(
            {
                "slot_key": asset.slot_key,
                "url": asset.image.url,
                "alt_text": asset.alt_text,
            }
        )

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        return JsonResponse({"error": "POST required."}, status=405)


@require_POST
@staff_member_required
def media_sync(request: HttpRequest) -> HttpResponse:
    """Re-derive the slot inventory from the current City/ProjectType/CaseCard rows."""
    if not request.user.has_perm("cms.change_mediaasset"):
        raise PermissionDenied

    created, pruned = sync_media_slots()
    messages.success(
        request,
        f"Slot sync complete — {created} added, {pruned} removed.",
    )
    return redirect("admin:studio_media")


# --- Publish Queue -----------------------------------------------------------


class PublishQueueView(StudioPageView):
    """Everything sitting in draft, across every content model, in one list."""

    title = "Publish queue"
    template_name = "studio/queue.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        groups = draft_groups()
        context.update(
            {
                "groups": groups,
                "total": sum(group.count for group in groups),
                "publish_url": reverse("admin:studio_queue_publish"),
            }
        )
        return context


@require_POST
@staff_member_required
def queue_publish(request: HttpRequest) -> HttpResponse:
    """Publish drafts: everything, one model (`model=app.model`), or one page (`scope=`).

    Iterates and calls `publish()` per object rather than a bulk `update()`. The
    per-save signals are what bump the content cache version and ping the frontend
    to revalidate; a bulk update would skip them and leave the live site stale.
    """
    target = request.POST.get("model", "")
    scope = request.POST.get("scope", "")
    published = 0

    for model in publishable_models():
        meta = model._meta
        if target and target != meta.label_lower:
            continue
        if not request.user.has_perm(f"{meta.app_label}.change_{meta.model_name}"):
            continue

        drafts = draft_queryset(model)
        if scope:
            # Only scoped blocks carry a page key; other publishables are page-agnostic.
            if not hasattr(model, "scope"):
                continue
            drafts = drafts.filter(scope=scope)

        for obj in drafts:
            obj.publish()
            published += 1

    if published:
        messages.success(request, f"Published {published} item{'s' if published != 1 else ''}.")
    else:
        messages.info(request, "Nothing to publish.")

    if scope:
        return redirect("admin:studio_page_composer", page_key=scope)
    return redirect("admin:studio_queue")
