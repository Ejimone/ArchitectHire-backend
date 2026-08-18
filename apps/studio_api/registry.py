"""Every record type the Studio edits that is *not* a page block or chrome row.

The 14 block models and 9 chrome models were the whole allowlist; everything else the
site renders — case studies, inspiration items, jobs, contact methods, policy sections,
the catalog, the jurisdiction prose, plans — was reachable only through Django admin.
Each entry here makes one model editable through the generic `records/` API and the
same draft → publish → revision machinery the blocks use, without a view per model.

A `CollectionSpec` says what the Studio cannot infer from the model class alone: which
page a row belongs to (for the publish queue), whether it is a child of another record,
which JSON columns have a known shape, which field is the row's title, and how to render
it the way the site does (`serializer`).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from django.apps import apps as django_apps
from django.db import models

from apps.catalog.serializers import (
    AddonSerializer,
    PlanSerializer,
    ProjectTypeDetailSerializer,
    RenderDeliverableSerializer,
    ServiceCategorySerializer,
    ServiceSerializer,
)
from apps.cms.serializers_editorial import (
    AuthorSerializer,
    CaseStudyDetailSerializer,
    CaseStudyImageSerializer,
    ContactMethodSerializer,
    InspirationItemSerializer,
    JobPostingSerializer,
    PerkSerializer,
    PolicyPageSerializer,
    PolicySectionSerializer,
)
from apps.jurisdictions.serializers import CityDetailSerializer, StateDetailSerializer

# JSON column shapes the inspector can render as structured editors instead of raw text.
LIST_OF_STRINGS = {"kind": "list", "item": "string"}


def list_of(**fields: str) -> dict:
    """A list of objects with the given string fields, e.g. `list_of(k="Label", v="Value")`."""
    return {"kind": "list", "item": "object", "fields": fields}


@dataclass(frozen=True)
class CollectionSpec:
    label: str
    name: str
    section: str
    verbose: str
    title_field: str
    search_fields: tuple[str, ...] = ()
    ordering: tuple[str, ...] = ("id",)
    #: FK field name on this model pointing at its parent record, if it is a child.
    parent: str | None = None
    #: Labels of child collections (their `parent` points back here).
    children: tuple[str, ...] = ()
    #: Which page key a row's edits are queued under. Called with a `value(name)` getter
    #: that reads the draft payload first and the live row second.
    scope: Callable[[Callable[[str], object]], str] = lambda value: ""
    #: The live URL of one row, or None. Called with the model instance.
    route: Callable[[object], str | None] = lambda obj: None
    #: The public serializer that renders a row the way the site sees it (`shape=public`).
    serializer: type | None = None
    #: Inbound rows (contact submissions, subscribers): readable, never writable.
    readonly: bool = False
    #: JSON field name → shape description.
    json_shapes: dict = field(default_factory=dict)
    #: The record's own page in the Studio tree, as a `<prefix>:<slug_field>` template.
    page_prefix: str | None = None
    page_slug_field: str = "slug"

    @property
    def model(self):
        return django_apps.get_model(self.label)

    @property
    def orderable(self) -> bool:
        return any(f.name == "sort_order" for f in self.model._meta.fields)

    @property
    def publishable(self) -> bool:
        names = {f.name for f in self.model._meta.fields}
        return "status" in names and "published_at" in names

    def page_key(self, obj) -> str | None:
        if not self.page_prefix:
            return None
        slug = getattr(obj, self.page_slug_field, "")
        return f"{self.page_prefix}:{slug}" if slug else None


def _fixed(scope: str):
    return lambda value: scope


def _by_slug(prefix: str, name: str = "slug"):
    def scope(value):
        slug = value(name) or ""
        return f"{prefix}:{slug}" if slug else prefix

    return scope


def _sub_plan_scope(value):
    return "expert-pricing" if value("group") == "pricing-page" else "for-experts"


def _policy_scope(value):
    return value("slug") or "privacy"


SPECS: list[CollectionSpec] = [
    # --- Editorial ---------------------------------------------------------------
    CollectionSpec(
        label="cms.casestudy",
        name="case-studies",
        section="Editorial",
        verbose="Case studies",
        title_field="title",
        search_fields=("title", "dek", "location"),
        ordering=("-published_at", "-created_at"),
        children=("cms.casestudyimage",),
        scope=_by_slug("case-study"),
        route=lambda obj: f"/case-studies/{obj.slug}" if obj.slug else None,
        serializer=CaseStudyDetailSerializer,
        json_shapes={
            "match_points": LIST_OF_STRINGS,
            "glance": list_of(k="Label", v="Value"),
            "card_stats": list_of(value="Value", key="Label"),
            "architect_tags": LIST_OF_STRINGS,
        },
        page_prefix="case-study",
    ),
    CollectionSpec(
        label="cms.casestudyimage",
        name="case-study-images",
        section="Editorial",
        verbose="Case study gallery images",
        title_field="caption",
        ordering=("sort_order", "id"),
        parent="case_study",
        scope=lambda value: "",  # resolved from the parent, see drafts.scope_for
        serializer=CaseStudyImageSerializer,
    ),
    CollectionSpec(
        label="cms.casestudycategory",
        name="case-study-categories",
        section="Editorial",
        verbose="Case study categories",
        title_field="name",
        search_fields=("name",),
        ordering=("sort_order", "id"),
        scope=_fixed("case-studies"),
    ),
    CollectionSpec(
        label="cms.inspirationitem",
        name="inspiration",
        section="Editorial",
        verbose="Inspiration items",
        title_field="title",
        search_fields=("title", "tag", "style"),
        ordering=("sort_order", "id"),
        scope=_fixed("inspiration"),
        route=lambda obj: "/inspiration",
        serializer=InspirationItemSerializer,
        json_shapes={"palette": {"kind": "list", "item": "color"}},
    ),
    CollectionSpec(
        label="cms.author",
        name="authors",
        section="Editorial",
        verbose="Authors",
        title_field="name",
        search_fields=("name", "role"),
        ordering=("name",),
        scope=_fixed("blog"),
        serializer=AuthorSerializer,
    ),
    CollectionSpec(
        label="cms.blogcategory",
        name="blog-categories",
        section="Editorial",
        verbose="Guide categories",
        title_field="name",
        search_fields=("name",),
        ordering=("sort_order", "id"),
        scope=_fixed("blog"),
    ),
    # --- Company ---------------------------------------------------------------
    CollectionSpec(
        label="cms.jobposting",
        name="jobs",
        section="Company",
        verbose="Job postings",
        title_field="title",
        search_fields=("title", "location", "employment_type"),
        ordering=("sort_order", "id"),
        scope=_fixed("careers"),
        route=lambda obj: "/careers",
        serializer=JobPostingSerializer,
    ),
    CollectionSpec(
        label="cms.department",
        name="departments",
        section="Company",
        verbose="Departments",
        title_field="name",
        search_fields=("name",),
        ordering=("sort_order", "id"),
        scope=_fixed("careers"),
    ),
    CollectionSpec(
        label="cms.perk",
        name="perks",
        section="Company",
        verbose="Perks",
        title_field="title",
        search_fields=("title",),
        ordering=("sort_order", "id"),
        scope=_fixed("careers"),
        route=lambda obj: "/careers",
        serializer=PerkSerializer,
    ),
    CollectionSpec(
        label="cms.contactmethod",
        name="contact-methods",
        section="Company",
        verbose="Contact methods",
        title_field="title",
        search_fields=("kind", "title"),
        ordering=("sort_order", "id"),
        scope=_fixed("contact"),
        route=lambda obj: "/contact",
        serializer=ContactMethodSerializer,
    ),
    CollectionSpec(
        label="cms.contacttopic",
        name="contact-topics",
        section="Company",
        verbose="Contact form topics",
        title_field="label",
        search_fields=("label",),
        ordering=("sort_order", "id"),
        scope=_fixed("contact"),
    ),
    CollectionSpec(
        label="cms.contactsubmission",
        name="contact-submissions",
        section="Inbox",
        verbose="Contact form submissions",
        title_field="name",
        search_fields=("name", "email", "topic", "message"),
        ordering=("-created_at",),
        readonly=True,
    ),
    CollectionSpec(
        label="cms.newslettersubscriber",
        name="newsletter-subscribers",
        section="Inbox",
        verbose="Newsletter subscribers",
        title_field="email",
        search_fields=("email", "source"),
        ordering=("-created_at",),
        readonly=True,
    ),
    CollectionSpec(
        label="cms.policypage",
        name="policies",
        section="Company",
        verbose="Policy pages",
        title_field="title",
        search_fields=("title", "slug"),
        ordering=("slug",),
        children=("cms.policysection",),
        scope=_policy_scope,
        route=lambda obj: f"/{obj.slug}" if obj.slug in ("privacy", "terms") else None,
        serializer=PolicyPageSerializer,
    ),
    CollectionSpec(
        label="cms.policysection",
        name="policy-sections",
        section="Company",
        verbose="Policy sections",
        title_field="heading",
        search_fields=("heading", "anchor"),
        ordering=("sort_order", "id"),
        parent="page",
        serializer=PolicySectionSerializer,
    ),
    # --- Catalog -----------------------------------------------------------------
    CollectionSpec(
        label="catalog.servicecategory",
        name="service-categories",
        section="Catalog",
        verbose="Service categories",
        title_field="name",
        search_fields=("name", "tagline"),
        ordering=("sort_order", "id"),
        children=("catalog.service",),
        scope=_fixed("services"),
        route=lambda obj: "/services#catalog",
        serializer=ServiceCategorySerializer,
    ),
    CollectionSpec(
        label="catalog.service",
        name="services",
        section="Catalog",
        verbose="Services",
        title_field="name",
        search_fields=("name", "description", "price_display"),
        ordering=("sort_order", "id"),
        parent="category",
        scope=_fixed("services"),
        route=lambda obj: "/services#catalog",
        serializer=ServiceSerializer,
        page_prefix="service",
    ),
    CollectionSpec(
        label="catalog.projecttype",
        name="project-types",
        section="Catalog",
        verbose="Project types",
        title_field="name",
        search_fields=("name", "h1", "kicker"),
        ordering=("sort_order", "id"),
        scope=_by_slug("project-type"),
        route=lambda obj: f"/projects/{obj.slug}" if obj.slug else None,
        serializer=ProjectTypeDetailSerializer,
        json_shapes={
            "stats": list_of(value="Value", label="Label"),
            "includes": LIST_OF_STRINGS,
            "price_notes": LIST_OF_STRINGS,
            "steps": list_of(title="Title", description="Description"),
            "related": LIST_OF_STRINGS,
        },
        page_prefix="project-type",
    ),
    CollectionSpec(
        label="catalog.plan",
        name="plans",
        section="Catalog",
        verbose="Contract plans",
        title_field="title",
        search_fields=("title", "tag"),
        ordering=("sort_order", "id"),
        scope=_fixed("landing"),
        route=lambda obj: "/#pricing",
        serializer=PlanSerializer,
        json_shapes={"points": LIST_OF_STRINGS},
    ),
    CollectionSpec(
        label="catalog.addon",
        name="addons",
        section="Catalog",
        verbose="Estimate add-ons",
        title_field="label",
        search_fields=("label", "sub"),
        ordering=("sort_order", "id"),
        scope=_fixed("get-started"),
        serializer=AddonSerializer,
    ),
    CollectionSpec(
        label="catalog.renderdeliverable",
        name="render-deliverables",
        section="Catalog",
        verbose="Render price matrix",
        title_field="name",
        search_fields=("name", "unit"),
        ordering=("sort_order", "id"),
        scope=_fixed("3d-visualization"),
        route=lambda obj: "/services/3d-visualization",
        serializer=RenderDeliverableSerializer,
    ),
    CollectionSpec(
        label="payments.subscriptionplan",
        name="subscription-plans",
        section="Catalog",
        verbose="Subscription plans",
        title_field="name",
        search_fields=("name", "key", "tagline"),
        ordering=("group", "sort_order"),
        scope=_sub_plan_scope,
        route=lambda obj: (
            "/for-experts/pricing" if obj.group == "pricing-page" else "/for-experts#pricing"
        ),
        json_shapes={"points": LIST_OF_STRINGS},
    ),
    # --- Locations ---------------------------------------------------------------
    CollectionSpec(
        label="jurisdictions.state",
        name="states",
        section="Locations",
        verbose="States",
        title_field="name",
        search_fields=("name", "code"),
        ordering=("name",),
        scope=_by_slug("state", "code"),
        route=lambda obj: f"/jurisdictions/{obj.code.lower()}" if obj.code else None,
        serializer=StateDetailSerializer,
        json_shapes={
            "permit_steps": list_of(title="Title", duration="Duration", description="Description")
        },
        page_prefix="state",
        page_slug_field="code",
    ),
    CollectionSpec(
        label="jurisdictions.city",
        name="cities",
        section="Locations",
        verbose="Cities",
        title_field="name",
        search_fields=("name", "county"),
        ordering=("name",),
        scope=_by_slug("city"),
        route=lambda obj: f"/cities/{obj.slug}" if obj.slug else None,
        serializer=CityDetailSerializer,
        json_shapes={
            "permit_facts": list_of(k="Label", v="Value"),
            "service_areas": LIST_OF_STRINGS,
        },
        page_prefix="city",
    ),
    # --- Search ------------------------------------------------------------------
    CollectionSpec(
        label="search.popularsearch",
        name="popular-searches",
        section="Marketing",
        verbose="Popular searches",
        title_field="term",
        search_fields=("term", "href"),
        ordering=("sort_order", "id"),
        scope=_fixed("search"),
        route=lambda obj: "/search",
    ),
]

BY_LABEL: dict[str, CollectionSpec] = {spec.label: spec for spec in SPECS}
BY_NAME: dict[str, CollectionSpec] = {spec.name: spec for spec in SPECS}
COLLECTION_LABELS = frozenset(BY_LABEL)
WRITABLE_COLLECTION_LABELS = frozenset(label for label, s in BY_LABEL.items() if not s.readonly)


def spec_for(label_or_name: str) -> CollectionSpec | None:
    key = (label_or_name or "").lower()
    return BY_LABEL.get(key) or BY_NAME.get(key)


def parent_of(spec: CollectionSpec) -> CollectionSpec | None:
    if spec.parent is None:
        return None
    field_ = spec.model._meta.get_field(spec.parent)
    return BY_LABEL.get(field_.related_model._meta.label_lower)


def image_labels() -> frozenset[str]:
    """Collections with at least one file column — the ones the upload endpoint serves."""
    return frozenset(
        spec.label
        for spec in SPECS
        if any(isinstance(f, models.FileField) for f in spec.model._meta.fields)
    )
