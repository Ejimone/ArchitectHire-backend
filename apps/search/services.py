"""Search index building + querying."""

from django.db.models import Q

from .models import SearchIndexEntry

STATIC_PAGES = [
    ("How it works", "The client journey, end to end", "/#how"),
    ("Services", "The full three-tier services catalog", "/services"),
    ("For architects", "Apply to join the network", "/for-architects"),
    ("For service experts", "Drafters, 3D artists, engineers, permit pros", "/for-experts"),
    ("Guides", "Permits, pricing & plans, explained", "/guides"),
    ("Case studies", "Real projects, permit to keys", "/case-studies"),
    ("About", "What ArchitectHire is and how we work", "/about"),
    ("Careers", "Open roles", "/careers"),
    ("Contact", "Talk to the team", "/contact"),
    ("Jurisdiction database", "Permit complexity for all 52 US jurisdictions", "/jurisdictions"),
    ("Inspiration", "Browse finished work by style", "/inspiration"),
    ("Get started", "Instant estimate for your project", "/get-started"),
]


def rebuild_index() -> int:
    """Regenerate the whole index from source models. Returns entry count."""
    from apps.catalog.models import ProjectType, Service
    from apps.cms.models import BlogPost, CaseStudy
    from apps.jurisdictions.models import City

    entries: list[SearchIndexEntry] = []

    for service in Service.objects.select_related("category"):
        entries.append(
            SearchIndexEntry(
                category="Services",
                title=service.name,
                subtitle=f"{service.price_display} · {service.price_unit}".strip(" ·"),
                href=service.detail_href or "/services#catalog",
                keywords=f"{service.category.name} {service.description}",
            )
        )

    for project_type in ProjectType.objects.all():
        entries.append(
            SearchIndexEntry(
                category="Project types",
                title=project_type.name,
                subtitle=f"{project_type.sub} · {project_type.price_display}".strip(" ·"),
                href=f"/projects/{project_type.slug}",
                keywords=project_type.get_group_display(),
            )
        )

    for city in City.objects.select_related("state"):
        entries.append(
            SearchIndexEntry(
                category="Cities",
                title=f"{city.name}, {city.state.code}",
                subtitle=f"Architects licensed in {city.state.name}",
                href=f"/cities/{city.slug}",
                keywords=city.state.name,
            )
        )

    for post in BlogPost.objects.published():
        entries.append(
            SearchIndexEntry(
                category="Guides",
                title=post.title,
                subtitle=post.dek or post.excerpt[:120],
                href=f"/guides/{post.slug}",
                keywords=post.category.name if post.category else "",
            )
        )

    for case in CaseStudy.objects.published():
        entries.append(
            SearchIndexEntry(
                category="Case studies",
                title=case.title,
                subtitle=case.location,
                href=f"/case-studies/{case.slug}",
                keywords=case.excerpt,
            )
        )

    for title, subtitle, href in STATIC_PAGES:
        entries.append(
            SearchIndexEntry(category="Pages", title=title, subtitle=subtitle, href=href)
        )

    SearchIndexEntry.objects.all().delete()
    SearchIndexEntry.objects.bulk_create(entries)
    return len(entries)


def query_index(q: str, limit: int = 30) -> dict[str, list[dict]]:
    matches = SearchIndexEntry.objects.filter(
        Q(title__icontains=q) | Q(subtitle__icontains=q) | Q(keywords__icontains=q)
    )[:limit]
    grouped: dict[str, list[dict]] = {}
    for entry in matches:
        grouped.setdefault(entry.category, []).append(
            {"title": entry.title, "subtitle": entry.subtitle, "href": entry.href}
        )
    return grouped
