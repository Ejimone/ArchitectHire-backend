"""Omnisearch: the command palette's cross-model result provider.

Unfold's built-in model search only covers ModelAdmins that declare `search_fields`,
and returns a flat, unlabelled list. This adds two things the owner asked for:

* **Reach** — pages and image slots are searchable too, not just database rows.
* **Freshness** — `StudioAdminSite.search` drops Unfold's five-minute result cache
  before delegating, so a record saved seconds ago is findable immediately.

Registered as `UNFOLD["COMMAND"]["search_callback"]`.
"""

from django.db.models import Q
from django.http import HttpRequest
from django.urls import reverse
from unfold.dataclasses import SearchResult

# (model label, icon, search fields, description template field)
SEARCHABLE: list[tuple[str, str, list[str]]] = [
    ("cms.blogpost", "article", ["title", "excerpt", "dek"]),
    ("cms.casestudy", "auto_stories", ["title", "excerpt", "location"]),
    ("cms.copyblock", "format_quote", ["key", "text", "scope"]),
    ("cms.pageseo", "travel_explore", ["page_key", "title", "description"]),
    ("cms.faq", "help", ["question", "answer"]),
    ("cms.testimonial", "reviews", ["name", "quote", "role"]),
    ("cms.casecard", "gallery_thumbnail", ["title", "excerpt", "location"]),
    ("cms.inspirationitem", "palette", ["title", "tag", "style"]),
    ("cms.author", "person_edit", ["name", "role"]),
    ("cms.jobposting", "work_history", ["title", "location"]),
    ("catalog.service", "design_services", ["name", "description"]),
    ("catalog.projecttype", "home_work", ["name", "slug", "intro"]),
    ("jurisdictions.city", "location_city", ["name", "slug"]),
    ("jurisdictions.state", "map", ["name", "code"]),
    ("accounts.user", "person", ["email", "first_name", "last_name", "clerk_id"]),
    ("providers.architectprofile", "architecture", ["firm_name", "user__email"]),
    ("providers.expertprofile", "engineering", ["studio_name", "user__email"]),
    ("orders.order", "receipt_long", ["customer_email", "customer_name"]),
    ("payments.subscriptionplan", "loyalty", ["name", "key", "gateway_price_id"]),
]

PER_MODEL_LIMIT = 5


def _model_results(request: HttpRequest, term: str) -> list[SearchResult]:
    from django.apps import apps

    results: list[SearchResult] = []
    for label, icon, fields in SEARCHABLE:
        try:
            model = apps.get_model(label)
        except LookupError:  # pragma: no cover - guards a renamed model
            continue

        meta = model._meta
        if not request.user.has_perm(f"{meta.app_label}.view_{meta.model_name}"):
            continue

        predicate = Q()
        for field in fields:
            predicate |= Q(**{f"{field}__icontains": term})

        change_route = f"admin:{meta.app_label}_{meta.model_name}_change"
        for obj in model._default_manager.filter(predicate)[:PER_MODEL_LIMIT]:
            results.append(
                SearchResult(
                    title=str(obj),
                    description=str(meta.verbose_name).capitalize(),
                    link=reverse(change_route, args=[obj.pk]),
                    icon=icon,
                )
            )
    return results


def _page_results(term: str) -> list[SearchResult]:
    """Pages are not database rows, so they need their own pass."""
    from apps.studio.pages import all_pages

    results = []
    for ref in all_pages():
        if term in ref.key.lower() or term in ref.label.lower():
            results.append(
                SearchResult(
                    title=ref.label,
                    description=f"Page · {ref.key}",
                    link=ref.composer_url,
                    icon="web",
                )
            )
    return results[:8]


def _media_results(request: HttpRequest, term: str) -> list[SearchResult]:
    from apps.cms.models import MediaAsset

    if not request.user.has_perm("cms.view_mediaasset"):
        return []

    assets = MediaAsset.objects.filter(
        Q(slot_key__icontains=term) | Q(notes__icontains=term) | Q(alt_text__icontains=term)
    )[:PER_MODEL_LIMIT]
    return [
        SearchResult(
            title=asset.notes or asset.slot_key,
            description=f"Image slot · {asset.slot_key}",
            link=reverse("admin:cms_mediaasset_change", args=[asset.pk]),
            icon="image",
        )
        for asset in assets
    ]


def omnisearch(request: HttpRequest, term: str) -> list[SearchResult]:
    term = (term or "").strip().lower()
    if len(term) < 2:
        return []
    return _page_results(term) + _model_results(request, term) + _media_results(request, term)
