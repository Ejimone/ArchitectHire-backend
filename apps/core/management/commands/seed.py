"""Load design-extracted seed data (seeds/*.json) into the database.

Idempotent: uses update_or_create on natural keys, safe to re-run anytime,
including production. Regenerate the JSON from the design with:

    uv run python scripts/extract_seeds.py

Usage:
    manage.py seed --all
    manage.py seed --domain jurisdictions,catalog,cms
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SEEDS = Path(settings.BASE_DIR) / "seeds"

# Services whose deliverable carries a licensed stamp (the design's "stamp line").
STAMPED_SERVICE_SLUGS = {
    "structural-stamp-residential",
    "permit-set-small-residential",
    "full-adu-package",
    "custom-home-design",
    "commercial-tenant-improvement",
    "title-24-energy-modeling",
}


def load(name: str):
    path = SEEDS / f"{name}.json"
    if not path.exists():
        raise CommandError(f"Missing seed file {path}. Run scripts/extract_seeds.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = "Seed the database with the design's exact content"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--domain", type=str, default="")

    def handle(self, *args, **options):
        domains = (
            ["jurisdictions", "catalog", "cms"]
            if options["all"]
            else [d.strip() for d in options["domain"].split(",") if d.strip()]
        )
        if not domains:
            raise CommandError("Pass --all or --domain jurisdictions,catalog,cms")
        for domain in domains:
            handler = getattr(self, f"seed_{domain}", None)
            if handler is None:
                raise CommandError(f"Unknown domain '{domain}'")
            handler()
        self.stdout.write(self.style.SUCCESS(f"Seeded: {', '.join(domains)}"))

    # --- domains ------------------------------------------------------------

    def seed_jurisdictions(self):
        from apps.jurisdictions.models import City, State

        for row in load("jurisdictions"):
            State.objects.update_or_create(
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "complexity_score": row["score"],
                    "region": row["region"],
                    "largest_city": row["largest_city"],
                },
            )
        states_by_name = {s.name: s for s in State.objects.all()}
        for row in load("cities"):
            state = states_by_name.get(row["state"])
            if state is None:
                continue
            City.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "name": row["name"],
                    "state": state,
                    "architect_count": row["architect_count"],
                },
            )
        self.stdout.write(
            f"  jurisdictions: {State.objects.count()} states, {City.objects.count()} cities"
        )

    def seed_catalog(self):
        from apps.catalog.models import (
            Addon,
            DraftingConfig,
            EstimateConfig,
            Plan,
            ProjectType,
            RenderDeliverable,
            Service,
            ServiceCategory,
        )

        for order, group in enumerate(load("services")):
            category, _ = ServiceCategory.objects.update_or_create(
                slug=group["slug"],
                defaults={
                    "name": group["name"],
                    "icon": group["icon"],
                    "tagline": group["tagline"],
                    "has_detail": group["has_detail"],
                    "detail_href": group["detail_href"],
                    "sort_order": order,
                },
            )
            for sorder, svc in enumerate(group["services"]):
                Service.objects.update_or_create(
                    slug=svc["slug"],
                    defaults={
                        "category": category,
                        "name": svc["name"],
                        "description": svc["description"],
                        "price_display": svc["price_display"],
                        "price_unit": svc["price_unit"],
                        "detail_href": svc.get("detail_href", ""),
                        "requires_stamp": svc["slug"] in STAMPED_SERVICE_SLUGS,
                        "sort_order": sorder,
                    },
                )

        for order, addon in enumerate(load("addons")):
            Addon.objects.update_or_create(
                key=addon["key"],
                defaults={
                    "label": addon["label"],
                    "sub": addon["sub"],
                    "price": addon["price"],
                    "sort_order": order,
                },
            )

        for order, plan in enumerate(load("plans")):
            Plan.objects.update_or_create(
                key=plan["key"],
                defaults={
                    "tag": plan["tag"],
                    "title": plan["title"],
                    "blurb": plan["blurb"],
                    "points": plan["points"],
                    "cta_label": plan["cta_label"],
                    "is_recommended": plan["is_recommended"],
                    "sort_order": order,
                },
            )

        order = 0
        for group in load("project_types"):
            group_key = "residential" if group["group"] == "Residential" else "commercial"
            for item in group["items"]:
                ProjectType.objects.update_or_create(
                    slug=item["slug"],
                    defaults={
                        "group": group_key,
                        "name": item["name"],
                        "sub": item["sub"],
                        "price_display": item["price_display"],
                        "slot_id": item["slot_id"],
                        "image_hint": item["image_hint"],
                        "sort_order": order,
                    },
                )
                order += 1

        for order, row in enumerate(load("render_matrix")):
            RenderDeliverable.objects.update_or_create(
                name=row["deliverable"],
                defaults={
                    "unit": row["unit"],
                    "conceptual": row["conceptual"],
                    "professional": row["professional"],
                    "photoreal": row["photoreal"],
                    "sort_order": order,
                },
            )

        drafting = load("drafting_config")
        config = DraftingConfig.get_solo()
        for key, value in drafting.items():
            setattr(config, key, value)
        config.save()

        estimate = load("estimate_config")
        config = EstimateConfig.get_solo()
        for key, value in estimate.items():
            setattr(config, key, value)
        config.save()

        self.stdout.write(
            f"  catalog: {ServiceCategory.objects.count()} categories, "
            f"{Service.objects.count()} services, {Addon.objects.count()} addons, "
            f"{Plan.objects.count()} plans, {ProjectType.objects.count()} project types, "
            f"{RenderDeliverable.objects.count()} render rows"
        )

    def seed_cms(self):
        from apps.cms.models import FooterColumn, FooterLink, NavGroup, NavItem, SocialLink

        nav = load("nav")
        for order, group in enumerate(nav["services"]):
            nav_group, _ = NavGroup.objects.update_or_create(
                menu="services",
                heading=group["heading"],
                defaults={"sort_order": order},
            )
            self._sync_nav_items(nav_group, group["items"])

        projects_group, _ = NavGroup.objects.update_or_create(
            menu="projects", heading="", defaults={"sort_order": 0}
        )
        self._sync_nav_items(projects_group, nav["projects"])

        locations_group, _ = NavGroup.objects.update_or_create(
            menu="locations", heading="", defaults={"sort_order": 0}
        )
        self._sync_nav_items(locations_group, nav["locations"])

        footer = load("footer")
        for order, column in enumerate(footer["columns"]):
            col, _ = FooterColumn.objects.update_or_create(
                heading=column["heading"], defaults={"sort_order": order}
            )
            for lorder, link in enumerate(column["links"]):
                FooterLink.objects.update_or_create(
                    column=col,
                    label=link["label"],
                    defaults={"href": link["href"], "sort_order": lorder},
                )
        for order, social in enumerate(footer["social"]):
            SocialLink.objects.update_or_create(
                platform=social["platform"],
                defaults={"url": social["url"], "sort_order": order},
            )

        self.stdout.write(
            f"  cms: {NavGroup.objects.count()} nav groups, {NavItem.objects.count()} nav items, "
            f"{FooterColumn.objects.count()} footer columns, {SocialLink.objects.count()} socials"
        )

    @staticmethod
    def _sync_nav_items(group, items):
        from apps.cms.models import NavItem

        for order, item in enumerate(items):
            NavItem.objects.update_or_create(
                group=group,
                label=item["label"],
                defaults={
                    "href": item["href"],
                    "price_hint": item.get("price_hint", ""),
                    "sublabel": item.get("sublabel", ""),
                    "sort_order": order,
                },
            )
