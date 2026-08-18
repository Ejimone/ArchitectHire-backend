"""Page resolution for the Page Composer.

A "page" here is a scope key from `apps.core.scopes` — the same key that
`PageContentView` composes a JSON payload for, and the same key every scoped block
stores in its `scope` field. Static keys are declared in code; parameterised keys
(`city:oakland`, `blog-post:permit-timelines`) are derived from the rows that exist.

Reusing `apps.core.scopes` rather than mirroring it means the composer can never
offer a page the content API would reject.
"""

from dataclasses import dataclass, field

from django.urls import reverse

from apps.core.scopes import STATIC_PAGE_KEYS

# Frontend route per static page key. Mirrors the Next.js route table, cross-checked
# against apps/search/services.py:STATIC_PAGES and the design/marketing inventory.
# `None` means there is no public URL to preview: "chrome" is site-wide shell copy,
# and the signed-in app surfaces are behind Clerk auth.
STATIC_ROUTES: dict[str, str | None] = {
    "chrome": None,
    "landing": "/",
    "services-landing": "/services-landing",
    "services": "/services",
    "3d-visualization": "/services/3d-visualization",
    "cad-drafting": "/services/cad-drafting",
    "architect-landing": "/for-architects",
    "for-experts": "/for-experts",
    "expert-pricing": "/for-experts/pricing",
    "professional-tools": "/for-experts/tools",
    "projects": "/projects",
    "cities": "/cities",
    "blog": "/guides",
    "case-studies": "/case-studies",
    "about": "/about",
    "careers": "/careers",
    "contact": "/contact",
    "privacy": "/privacy",
    "terms": "/terms",
    "inspiration": "/inspiration",
    "jurisdiction-database": "/jurisdictions",
    "search": "/search",
    "get-started": "/get-started",
    "order-render": None,
    "order-drafting": None,
    "account": None,
    "matches": None,
    "engagement": None,
    "pro": None,
}

# Route template per dynamic scope prefix. A service has no page of its own on the site
# — the two service *templates* (3D visualization, CAD drafting) are static scopes, and
# every other service is a row inside the catalog on /services — so `service:*` has no
# route; the Studio edits it as a record instead.
DYNAMIC_ROUTES = {
    "project-type": "/projects/{slug}",
    "city": "/cities/{slug}",
    "state": "/jurisdictions/{slug}",
    "service": None,
    "blog-post": "/guides/{slug}",
    "case-study": "/case-studies/{slug}",
}

# Human labels, grouped the way the owner thinks about the site.
SECTIONS: list[tuple[str, list[str]]] = [
    ("Site shell", ["chrome"]),
    (
        "Marketing",
        [
            "landing",
            "about",
            "services-landing",
            "services",
            "3d-visualization",
            "cad-drafting",
            "projects",
            "get-started",
            "search",
        ],
    ),
    (
        "Recruiting",
        ["architect-landing", "for-experts", "expert-pricing", "professional-tools"],
    ),
    ("Editorial", ["blog", "case-studies", "inspiration"]),
    ("Locations", ["cities", "jurisdiction-database"]),
    ("Company", ["careers", "contact", "privacy", "terms"]),
    ("Ordering", ["order-render", "order-drafting"]),
    ("Signed-in app", ["account", "matches", "engagement", "pro"]),
]


@dataclass(frozen=True)
class PageRef:
    key: str
    label: str
    section: str
    route: str | None = None
    subtitle: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    #: `(model_label, pk)` for a dynamic page — the record whose row the scope belongs
    #: to, so the Studio can open it as a form even when it has no page to preview.
    record: tuple[str, int] | None = None

    @property
    def composer_url(self) -> str:
        return reverse("admin:studio_page_composer", kwargs={"page_key": self.key})

    @property
    def is_dynamic(self) -> bool:
        return ":" in self.key


def humanise(key: str) -> str:
    return key.replace("-", " ").replace(":", ": ").capitalize()


def route_for(page_key: str) -> str | None:
    """The public path this scope renders at, or None if it has no public URL."""
    if page_key in STATIC_ROUTES:
        return STATIC_ROUTES[page_key]
    prefix, _, slug = page_key.partition(":")
    template = DYNAMIC_ROUTES.get(prefix)
    if not template or not slug:
        return None
    return template.format(slug=slug.lower())


def static_pages() -> list[PageRef]:
    refs = []
    for section, keys in SECTIONS:
        for key in keys:
            refs.append(
                PageRef(key=key, label=humanise(key), section=section, route=route_for(key))
            )
    # Anything added to STATIC_PAGE_KEYS but not yet placed in SECTIONS still shows up,
    # so a new page key can never silently go missing from the composer.
    placed = {key for _, keys in SECTIONS for key in keys}
    for key in STATIC_PAGE_KEYS:
        if key not in placed:
            refs.append(
                PageRef(key=key, label=humanise(key), section="Other", route=route_for(key))
            )
    return refs


def dynamic_pages() -> list[PageRef]:
    """Parameterised scopes that actually have a row behind them."""
    from apps.catalog.models import ProjectType, Service
    from apps.cms.models_editorial import BlogPost, CaseStudy
    from apps.jurisdictions.models import City, State

    sources = [
        ("project-type", "Project types", ProjectType.objects.all(), "slug", "name"),
        ("city", "Cities", City.objects.select_related("state"), "slug", "name"),
        ("state", "States", State.objects.all(), "code", "name"),
        ("service", "Services", Service.objects.all(), "slug", "name"),
        ("blog-post", "Blog posts", BlogPost.objects.all(), "slug", "title"),
        ("case-study", "Case studies", CaseStudy.objects.all(), "slug", "title"),
    ]

    refs = []
    for prefix, section, queryset, slug_field, label_field in sources:
        label_lower = queryset.model._meta.label_lower
        for obj in queryset:
            slug = getattr(obj, slug_field, "")
            if not slug:
                continue
            key = f"{prefix}:{slug}"
            refs.append(
                PageRef(
                    key=key,
                    label=str(getattr(obj, label_field, slug)),
                    section=section,
                    route=route_for(key),
                    subtitle=key,
                    record=(label_lower, obj.pk),
                )
            )
    return refs


def all_pages() -> list[PageRef]:
    return static_pages() + dynamic_pages()


def find_page(page_key: str) -> PageRef | None:
    for ref in all_pages():
        if ref.key == page_key:
            return ref
    return None
