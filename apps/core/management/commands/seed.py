"""Load design-extracted seed data (seeds/*.json) into the database.

**A floor, not a sync.** On an empty database this loads the design's exact content.
On a database that has already been seeded it does nothing to the content domains —
the owner's edits in the Studio and the admin are the source of truth from then on,
and a deploy that re-runs `seed --all` (they all do) must never overwrite them. The
`media` and `searchindex` domains always run: filling empty slots and rebuilding the
index are already idempotent floors of their own. Pass `--overwrite` to deliberately
reset content to the seeds. Content corrections that must reach every environment ship
as data migrations, not as seed edits.

Regenerate the JSON from the design with:

    uv run python scripts/extract_seeds.py

Usage:
    manage.py seed --all
    manage.py seed --domain jurisdictions,catalog,cms
    manage.py seed --all --overwrite     # reset content to the seeds (destroys edits)
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

SEEDS = Path(settings.BASE_DIR) / "seeds"

# Block types a patch file may target, with the fields that identify a row
# within its (scope, group). Mirrors cms.views.BLOCK_REGISTRY.
BLOCK_NATURAL_KEYS = {
    "faqs": ["question"],
    "stats": ["value", "label"],
    "steps": ["title"],
    "testimonials": ["name"],
    "value_props": ["title"],
    "trust_logos": ["name"],
    "credential_badges": ["label"],
    "use_cases": ["title"],
    "personas": ["title"],
    "principles": ["title"],
    "carousel": ["caption"],
    "case_cards": ["title"],
    "estimate_teaser": ["label"],
    "feature_matrix": ["label"],
}

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


def load_optional(name: str):
    path = SEEDS / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# Domains that are skipped once they have run, unless --overwrite. Everything in them is
# owner-editable content; a second run would replace edits with the design's originals.
FLOOR_DOMAINS = ("jurisdictions", "catalog", "cms", "providers", "payments", "content")


class Command(BaseCommand):
    help = "Seed the database with the design's exact content (a floor — never overwrites edits)"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--domain", type=str, default="")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help=(
                "Reset content domains to the seeds even where they have already been "
                "loaded. Destroys edits made in the Studio and the admin."
            ),
        )

    def handle(self, *args, **options):
        from apps.cms.models import SeedRun

        domains = (
            [
                "jurisdictions",
                "catalog",
                "cms",
                "providers",
                "payments",
                "content",
                "media",
                "searchindex",
            ]
            if options["all"]
            else [d.strip() for d in options["domain"].split(",") if d.strip()]
        )
        if not domains:
            raise CommandError("Pass --all or --domain jurisdictions,catalog,cms")
        overwrite = options.get("overwrite", False)
        ran = []
        for domain in domains:
            handler = getattr(self, f"seed_{domain}", None)
            if handler is None:
                raise CommandError(f"Unknown domain '{domain}'")
            if (
                domain in FLOOR_DOMAINS
                and not overwrite
                and SeedRun.objects.filter(domain=domain).exists()
            ):
                self.stdout.write(
                    f"  {domain}: already seeded — edits made since are kept "
                    "(pass --overwrite to reset to the seeds)"
                )
                continue
            handler()
            if domain in FLOOR_DOMAINS:
                SeedRun.objects.update_or_create(domain=domain)
            ran.append(domain)
        self.stdout.write(self.style.SUCCESS(f"Seeded: {', '.join(ran) or 'nothing new'}"))

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

        # Per-type landing content, extracted from the design's `projects` map.
        landing = load_optional("project_landing") or {}
        by_name = {pt.name: pt for pt in ProjectType.objects.all()}
        for design_name, row in landing.items():
            project_type = by_name.get(design_name)
            if project_type is None:
                continue
            ProjectType.objects.filter(pk=project_type.pk).update(
                short_name=row.get("short", ""),
                kicker=row.get("kicker", ""),
                h1=row.get("h1", ""),
                intro=row.get("intro", ""),
                body=row.get("body", ""),
                price_display=row.get("price", project_type.price_display),
                price_range=row.get("range", ""),
                bar_pct=row.get("bar", 0),
                stats=row.get("stats", []),
                includes=row.get("includes", []),
                price_notes=row.get("priceNotes", []),
                steps=row.get("steps", []),
                image_hint=row.get("heroPh", project_type.image_hint),
            )

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

    # --- content domain (design-extracted copy, blocks, editorial, SEO) -----

    def seed_content(self):
        self._seed_copy()
        self._seed_scoped_blocks()
        self._seed_editorial()
        self._seed_seo()
        self._seed_patches()

    def _seed_patches(self):
        """Apply seeds/patches/*.json — content the design implies but the
        extracted seeds don't cover (per-page chrome, gallery cards, the
        landing records for project types the design only templated once),
        plus copy the extractor captured from a superseded revision of the
        design and therefore still re-seeds with stale wording.

        Kept separate from the extracted seeds so re-running the extractor
        never clobbers them, and so the owner can see exactly what was authored
        by hand: each file carries a `_note` explaining its gaps.

        A file may declare, in this order of application:

        ``delete``   {block_type: [{scope, group?, <natural key fields>}]} —
                     removes rows whose natural key the design renamed, so the
                     extracted seed's version doesn't linger beside the new one.
        ``copy``     CopyBlock rows.
        ``blocks``   scoped block rows.
        ``plans``    catalog.Plan rows, keyed on ``key``.
        ``service_categories``  catalog.ServiceCategory rows, keyed on ``slug``.
        ``page_seo`` PageSEO rows, keyed on ``page_key``.
        ``editorial``  authors, blog posts/blocks/bodies, case studies,
                     case study galleries and policy sections.
        ``project_types`` / ``cities`` / ``states``  partial record updates.
        """
        from apps.catalog.models import Plan, ProjectType, ServiceCategory
        from apps.cms.models import CopyBlock, PageSEO
        from apps.cms.views import BLOCK_REGISTRY
        from apps.jurisdictions.models import City, State

        block_models = {name: model for name, model, _ in BLOCK_REGISTRY}
        directory = SEEDS / "patches"
        if not directory.is_dir():
            return

        totals = {"copy": 0, "blocks": 0, "records": 0, "deleted": 0}
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))

            for name, rows in data.get("delete", {}).items():
                model = block_models.get(name)
                if model is None:
                    raise CommandError(f"{path.name}: unknown block type '{name}'")
                for row in rows:
                    deleted, _ = model.objects.filter(**row).delete()
                    totals["deleted"] += deleted

            for row in data.get("copy", []):
                CopyBlock.objects.update_or_create(
                    scope=row["scope"],
                    key=row["key"],
                    defaults={"text": row.get("text", ""), "href": row.get("href", "")},
                )
                totals["copy"] += 1

            for name, rows in data.get("blocks", {}).items():
                model = block_models.get(name)
                if model is None:
                    raise CommandError(f"{path.name}: unknown block type '{name}'")
                natural = BLOCK_NATURAL_KEYS[name]
                for row in rows:
                    lookup = {field: row[field] for field in natural}
                    defaults = {
                        key: value
                        for key, value in row.items()
                        if key not in {"scope", "sort", *natural}
                    }
                    defaults["sort_order"] = row.get("sort", 0)
                    defaults.pop("group", None)
                    model.objects.update_or_create(
                        scope=row["scope"], group=row.get("group", ""), **lookup, defaults=defaults
                    )
                    totals["blocks"] += 1

            for row in data.get("plans", []):
                fields = {k: v for k, v in row.items() if k != "key"}
                totals["records"] += Plan.objects.filter(key=row["key"]).update(**fields)

            for row in data.get("service_categories", []):
                fields = {k: v for k, v in row.items() if k != "slug"}
                totals["records"] += ServiceCategory.objects.filter(slug=row["slug"]).update(
                    **fields
                )

            for row in data.get("page_seo", []):
                fields = {k: v for k, v in row.items() if k != "page_key"}
                totals["records"] += PageSEO.objects.filter(page_key=row["page_key"]).update(
                    **fields
                )

            totals["records"] += self._patch_editorial(data.get("editorial", {}))

            for row in data.get("project_types", []):
                fields = {k: v for k, v in row.items() if k != "slug"}
                totals["records"] += ProjectType.objects.filter(slug=row["slug"]).update(**fields)

            for row in data.get("cities", []):
                fields = {k: v for k, v in row.items() if k != "slug"}
                totals["records"] += City.objects.filter(slug=row["slug"]).update(**fields)

            for row in data.get("states", []):
                fields = {k: v for k, v in row.items() if k != "code"}
                totals["records"] += State.objects.filter(code=row["code"]).update(**fields)

        self.stdout.write(
            f"  patches: {totals['copy']} copy, {totals['blocks']} blocks, "
            f"{totals['records']} records, {totals['deleted']} removed"
        )

    @staticmethod
    def _patch_editorial(data):
        """Partial updates to editorial records seeded from content_editorial.json.

        Blog body rows carry no natural key of their own, so they are addressed
        by ``post`` slug + ``sort_order`` — the order ``_seed_editorial`` writes
        them in, which is the order they appear in the article.

        ``authors``, ``blog_bodies`` and ``case_study_galleries`` author whole
        records rather than patching fields, for the articles and projects the
        extracted seeds left as a headline with no body: an author the extract
        never captured, an article body ``content_editorial.json`` has no
        ``blocks`` list for, and the gallery rows a case study needs before its
        design's photo grid renders at all. Each replaces the record's child
        rows outright, so re-running the seeder is idempotent.
        """
        from apps.cms.models import (
            Author,
            BlogContentBlock,
            BlogPost,
            CaseStudy,
            CaseStudyCategory,
            CaseStudyImage,
            PolicyPage,
            PolicySection,
        )

        updated = 0
        for row in data.get("authors", []):
            Author.objects.update_or_create(
                name=row["name"],
                defaults={k: v for k, v in row.items() if k != "name"},
            )
            updated += 1

        for row in data.get("blog_posts", []):
            fields = {k: v for k, v in row.items() if k != "slug"}
            updated += BlogPost.objects.filter(slug=row["slug"]).update(**fields)

        for row in data.get("blog_blocks", []):
            fields = {k: v for k, v in row.items() if k not in {"post", "sort_order"}}
            updated += BlogContentBlock.objects.filter(
                post__slug=row["post"], sort_order=row["sort_order"]
            ).update(**fields)

        for row in data.get("blog_bodies", []):
            post = BlogPost.objects.filter(slug=row["post"]).first()
            if post is None:
                continue
            if row.get("author"):
                post.author = Author.objects.filter(name=row["author"]).first()
                post.save(update_fields=["author"])
            post.content_blocks.all().delete()
            BlogContentBlock.objects.bulk_create(
                BlogContentBlock(
                    post=post,
                    kind=block.get("kind", "paragraph"),
                    text=block.get("text", ""),
                    attribution=block.get("attribution", ""),
                    cta_label=block.get("cta_label", ""),
                    cta_href=block.get("cta_href", ""),
                    sort_order=order,
                )
                for order, block in enumerate(row.get("blocks", []))
            )
            updated += 1

        for row in data.get("case_studies", []):
            fields = {k: v for k, v in row.items() if k != "slug"}
            if "category" in fields:
                # Addressed by name, like content_editorial.json does, so a patch
                # never has to name a primary key that a fresh seed reassigns.
                fields["category"] = CaseStudyCategory.objects.filter(
                    name=fields["category"]
                ).first()
            updated += CaseStudy.objects.filter(slug=row["slug"]).update(**fields)

        for row in data.get("case_study_galleries", []):
            case_study = CaseStudy.objects.filter(slug=row["case_study"]).first()
            if case_study is None:
                continue
            case_study.gallery.all().delete()
            CaseStudyImage.objects.bulk_create(
                CaseStudyImage(
                    case_study=case_study,
                    caption=image.get("caption", ""),
                    sort_order=order,
                )
                for order, image in enumerate(row.get("images", []))
            )
            updated += 1

        for row in data.get("policy_sections", []):
            fields = {k: v for k, v in row.items() if k not in {"page", "anchor"}}
            updated += PolicySection.objects.filter(
                page__slug=row["page"], anchor=row["anchor"]
            ).update(**fields)

        for row in data.get("policy_pages", []):
            page, _created = PolicyPage.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "title": row.get("title", ""),
                    "effective_date": row.get("effective_date"),
                },
            )
            for section in row.get("sections", []):
                PolicySection.objects.update_or_create(
                    page=page,
                    anchor=section["anchor"],
                    defaults={
                        "heading": section.get("heading", ""),
                        "body": section.get("body", ""),
                        "sort_order": section.get("sort", 0),
                    },
                )
            updated += 1

        return updated

    def _seed_copy(self):
        from apps.cms.models import CopyBlock

        rows = load_optional("content_copy")
        if rows is None:
            self.stdout.write(self.style.WARNING("  content_copy.json missing — skipped"))
            return
        for row in rows:
            CopyBlock.objects.update_or_create(
                scope=row["scope"],
                key=row["key"],
                defaults={"text": row.get("text", ""), "href": row.get("href", "")},
            )
        self.stdout.write(f"  copy: {CopyBlock.objects.count()} blocks")

    def _seed_scoped_blocks(self):
        from apps.cms.models import (
            FAQ,
            CaseCard,
            CredentialBadge,
            EstimateTeaserOption,
            HeroCarouselSlide,
            Persona,
            Principle,
            Stat,
            Step,
            Testimonial,
            TrustLogo,
            UseCase,
            ValueProp,
        )

        data = load_optional("content_blocks")
        if data is None:
            self.stdout.write(self.style.WARNING("  content_blocks.json missing — skipped"))
            return

        def sync(model, rows, natural_fields, extra=lambda r: {}):
            for row in rows:
                lookup = {f: row[f] for f in natural_fields}
                defaults = {
                    "sort_order": row.get("sort", 0),
                    "group": row.get("group", ""),
                    **extra(row),
                }
                model.objects.update_or_create(scope=row["scope"], **lookup, defaults=defaults)

        sync(FAQ, data.get("faqs", []), ["question"], lambda r: {"answer": r["answer"]})
        sync(Stat, data.get("stats", []), ["value", "label"])
        sync(
            Step,
            data.get("steps", []),
            ["title"],
            lambda r: {"description": r.get("description", "")},
        )
        sync(
            Testimonial,
            data.get("testimonials", []),
            ["name"],
            lambda r: {
                "quote": r["quote"],
                "role": r.get("role", ""),
                "audience": r.get("audience", "client"),
            },
        )
        sync(
            ValueProp,
            data.get("value_props", []),
            ["title"],
            lambda r: {"icon": r.get("icon", ""), "description": r.get("description", "")},
        )
        sync(TrustLogo, data.get("trust_logos", []), ["name"])
        sync(CredentialBadge, data.get("credential_badges", []), ["label"])
        sync(
            UseCase,
            data.get("use_cases", []),
            ["title"],
            lambda r: {
                "icon": r.get("icon", ""),
                "description": r.get("description", ""),
                "cta_label": r.get("cta_label", ""),
                "href": r.get("href", ""),
            },
        )
        sync(
            Persona,
            data.get("personas", []),
            ["title"],
            lambda r: {
                "kicker": r.get("kicker", ""),
                "body": r.get("body", ""),
                "points": "\n".join(r.get("points", [])),
                "cta_label": r.get("cta_label", ""),
                "cta_href": r.get("cta_href", ""),
            },
        )
        sync(
            Principle, data.get("principles", []), ["title"], lambda r: {"body": r.get("body", "")}
        )
        sync(
            HeroCarouselSlide,
            data.get("carousel", []),
            ["caption"],
            lambda r: {"name": r.get("name", "")},
        )
        sync(
            CaseCard,
            data.get("case_cards", []),
            ["title"],
            lambda r: {
                "category_tag": r.get("category_tag", ""),
                "location": r.get("location", ""),
                "excerpt": r.get("excerpt", ""),
                "href": r.get("href", ""),
                "stat1_value": r.get("stat1_value", ""),
                "stat1_label": r.get("stat1_label", ""),
                "stat2_value": r.get("stat2_value", ""),
                "stat2_label": r.get("stat2_label", ""),
            },
        )
        sync(
            EstimateTeaserOption,
            data.get("estimate_teaser", []),
            ["label"],
            lambda r: {
                "price_range": r.get("price_range", ""),
                "bar_pct": r.get("bar_pct", 0),
                "includes": "\n".join(r.get("includes", [])),
            },
        )
        self.stdout.write(
            f"  blocks: {FAQ.objects.count()} faqs, {Stat.objects.count()} stats, "
            f"{Step.objects.count()} steps, {Testimonial.objects.count()} testimonials, "
            f"{ValueProp.objects.count()} value props"
        )

    def _seed_editorial(self):
        from django.utils import timezone

        from apps.cms.models import (
            Author,
            BlogCategory,
            BlogContentBlock,
            BlogPost,
            CaseStudy,
            CaseStudyCategory,
            ContactMethod,
            ContactTopic,
            Department,
            InspirationItem,
            JobPosting,
            Perk,
            PolicyPage,
            PolicySection,
        )
        from apps.search.models import PopularSearch

        data = load_optional("content_editorial")
        if data is None:
            self.stdout.write(self.style.WARNING("  content_editorial.json missing — skipped"))
            return

        for order, cat in enumerate(data.get("blog_categories", [])):
            BlogCategory.objects.update_or_create(
                slug=cat["slug"], defaults={"name": cat["name"], "sort_order": order}
            )
        for author in data.get("authors", []):
            Author.objects.update_or_create(
                name=author["name"],
                defaults={"role": author.get("role", ""), "bio": author.get("bio", "")},
            )
        categories = {c.name: c for c in BlogCategory.objects.all()}
        authors = {a.name: a for a in Author.objects.all()}
        now = timezone.now()
        for post_data in data.get("blog_posts", []):
            post, _ = BlogPost.objects.update_or_create(
                slug=post_data["slug"],
                defaults={
                    "title": post_data["title"],
                    "dek": post_data.get("dek", ""),
                    "excerpt": post_data.get("excerpt", ""),
                    "category": categories.get(post_data.get("category", "")),
                    "author": authors.get(post_data.get("author", "")),
                    "read_time": post_data.get("read_time", ""),
                    "is_featured": post_data.get("is_featured", False),
                    "status": "published",
                    "published_at": now,
                },
            )
            if post_data.get("blocks"):
                post.content_blocks.all().delete()
                for order, block in enumerate(post_data["blocks"]):
                    BlogContentBlock.objects.create(
                        post=post,
                        kind=block.get("kind", "paragraph"),
                        text=block.get("text", ""),
                        attribution=block.get("attribution", ""),
                        cta_label=block.get("cta_label", ""),
                        cta_href=block.get("cta_href", ""),
                        sort_order=order,
                    )

        for order, cat in enumerate(data.get("case_study_categories", [])):
            CaseStudyCategory.objects.update_or_create(
                slug=cat["slug"], defaults={"name": cat["name"], "sort_order": order}
            )
        cs_categories = {c.name: c for c in CaseStudyCategory.objects.all()}
        for cs in data.get("case_studies", []):
            CaseStudy.objects.update_or_create(
                slug=cs["slug"],
                defaults={
                    "title": cs["title"],
                    "dek": cs.get("dek", ""),
                    "location": cs.get("location", ""),
                    "excerpt": cs.get("excerpt", ""),
                    "category": cs_categories.get(cs.get("category", "")),
                    "card_stats": cs.get("card_stats", []),
                    "is_featured": cs.get("is_featured", False),
                    "brief": cs.get("brief", ""),
                    "challenge1": cs.get("challenge1", ""),
                    "challenge2": cs.get("challenge2", ""),
                    "match_narrative": cs.get("match_narrative", ""),
                    "match_points": cs.get("match_points", []),
                    "quote": cs.get("quote", ""),
                    "quote_by": cs.get("quote_by", ""),
                    "outcome1": cs.get("outcome1", ""),
                    "outcome2": cs.get("outcome2", ""),
                    "glance": cs.get("glance", []),
                    "architect_name": cs.get("architect_name", ""),
                    "architect_role": cs.get("architect_role", ""),
                    "architect_bio": cs.get("architect_bio", ""),
                    "architect_tags": cs.get("architect_tags", []),
                    "status": "published",
                    "published_at": now,
                },
            )

        for order, name in enumerate(data.get("departments", [])):
            Department.objects.update_or_create(name=name, defaults={"sort_order": order})
        departments = {d.name: d for d in Department.objects.all()}
        for order, perk in enumerate(data.get("perks", [])):
            Perk.objects.update_or_create(
                title=perk["title"],
                defaults={"description": perk.get("description", ""), "sort_order": order},
            )
        for order, job in enumerate(data.get("jobs", [])):
            JobPosting.objects.update_or_create(
                title=job["title"],
                defaults={
                    "department": departments.get(job.get("department", "")),
                    "location": job.get("location", ""),
                    "employment_type": job.get("employment_type", ""),
                    "status": "published",
                    "published_at": now,
                    "sort_order": order,
                },
            )

        for order, method in enumerate(data.get("contact_methods", [])):
            ContactMethod.objects.update_or_create(
                kind=method["kind"],
                defaults={
                    "title": method.get("title", ""),
                    "description": method.get("description", ""),
                    "link_label": method.get("link_label", ""),
                    "href": method.get("href", ""),
                    "sort_order": order,
                },
            )
        for order, topic in enumerate(data.get("contact_topics", [])):
            ContactTopic.objects.update_or_create(label=topic, defaults={"sort_order": order})

        for policy in data.get("policies", []):
            page, _ = PolicyPage.objects.update_or_create(
                slug=policy["slug"], defaults={"title": policy["title"]}
            )
            for order, section in enumerate(policy.get("sections", [])):
                PolicySection.objects.update_or_create(
                    page=page,
                    anchor=section["anchor"],
                    defaults={
                        "heading": section["heading"],
                        "body": section.get("body", ""),
                        "sort_order": order,
                    },
                )

        for order, item in enumerate(data.get("inspiration", [])):
            InspirationItem.objects.update_or_create(
                title=item["title"],
                defaults={
                    "tag": item.get("tag", ""),
                    "style": item.get("style", ""),
                    "palette": item.get("palette", []),
                    "masonry_height": item.get("masonry_height", 280),
                    "likes_count": item.get("likes", 0),
                    "status": "published",
                    "published_at": now,
                    "sort_order": order,
                },
            )

        for order, search in enumerate(data.get("popular_searches", [])):
            PopularSearch.objects.update_or_create(
                term=search["term"],
                defaults={"href": search.get("href", ""), "sort_order": order},
            )

        self.stdout.write(
            f"  editorial: {BlogPost.objects.count()} posts, "
            f"{CaseStudy.objects.count()} case studies, {JobPosting.objects.count()} jobs, "
            f"{InspirationItem.objects.count()} inspiration items"
        )

    def _seed_seo(self):
        from apps.catalog.models import ProjectType
        from apps.cms.models import PageSEO
        from apps.jurisdictions.models import City, State

        data = load_optional("content_seo")
        if data is None:
            self.stdout.write(self.style.WARNING("  content_seo.json missing — skipped"))
            return

        for row in data.get("page_seo", []):
            PageSEO.objects.update_or_create(
                page_key=row["page_key"],
                defaults={"title": row.get("title", ""), "description": row.get("description", "")},
            )

        for pt in data.get("project_types", []):
            ProjectType.objects.filter(slug=pt["slug"]).update(
                short_name=pt.get("short_name", ""),
                kicker=pt.get("kicker", ""),
                h1=pt.get("h1", ""),
                intro=pt.get("intro", ""),
                body=pt.get("body", ""),
                price_range=pt.get("price_range", ""),
                bar_pct=pt.get("bar_pct", 0),
                stats=pt.get("stats", []),
                includes=pt.get("includes", []),
                price_notes=pt.get("price_notes", []),
                steps=pt.get("steps", []),
                related=pt.get("related", []),
            )

        for city_data in data.get("cities", []):
            City.objects.filter(slug=city_data["slug"]).update(
                intro=city_data.get("intro", ""),
                body1=city_data.get("body1", ""),
                body2=city_data.get("body2", ""),
                permit_facts=city_data.get("permit_facts", []),
                service_areas=city_data.get("service_areas", []),
            )

        for state_data in data.get("states", []):
            State.objects.filter(code=state_data["code"]).update(
                intro=state_data.get("intro", ""),
                body1=state_data.get("body1", ""),
                body2=state_data.get("body2", ""),
                permit_steps=state_data.get("permit_steps", []),
            )

        self.stdout.write(f"  seo: {PageSEO.objects.count()} page seo rows")

    def seed_searchindex(self):
        from apps.search.services import rebuild_index

        count = rebuild_index()
        self.stdout.write(f"  search index: {count} entries")

    def seed_providers(self):
        """The 6 expert disciplines (design: For Experts + Expert Account)."""
        from apps.providers.models import Discipline

        disciplines = [
            (
                "cad-drafting",
                "CAD drafting",
                "Drawings from sketches & redlines",
                "$65–90/hr",
                "NO LICENSE",
                False,
                False,
            ),
            (
                "3d-visualization",
                "3D & visualization",
                "Renders, floor plans, walkthroughs",
                "$99–4,000",
                "NO LICENSE",
                False,
                False,
            ),
            (
                "3d-scanning-bim",
                "3D scanning & BIM",
                "Point clouds & scan-to-BIM",
                "$0.20–10/sf",
                "NO LICENSE",
                False,
                True,
            ),
            (
                "structural-mep",
                "Structural / MEP engineering",
                "Calcs & licensed stamps",
                "from $1,500",
                "LICENSE REQ",
                True,
                False,
            ),
            (
                "energy-title-24",
                "Energy / Title-24",
                "Compliance modeling",
                "from $300",
                "CERTIFIED",
                True,
                False,
            ),
            (
                "permit-zoning",
                "Permit & zoning",
                "Expediting & entitlements",
                "$500–20k+",
                "SPECIALIST",
                True,
                False,
            ),
        ]
        for order, (key, name, description, rate, tag, lic, onsite) in enumerate(disciplines):
            Discipline.objects.update_or_create(
                key=key,
                defaults={
                    "name": name,
                    "description": description,
                    "typical_rate": rate,
                    "licensure_tag": tag,
                    "requires_license": lic,
                    "requires_onsite": onsite,
                    "sort_order": order,
                },
            )
        self.stdout.write(f"  providers: {Discipline.objects.count()} disciplines")

    def seed_media(self):
        """One MediaAsset row per image slot, then stock imagery into the empty ones.

        Filling matters as much as creating. An empty inventory is what made the site
        render as a grid of crosshatch placeholders on every deploy; the committed set in
        `seeds/media/` means a fresh environment comes up looking finished. Slots the
        owner has already filled are never overwritten.
        """
        from apps.cms.models import MediaAsset
        from apps.cms.slots import attach_seed_images, expected_media_slots, sync_media_slots

        created, pruned = sync_media_slots()
        # Refresh the where-this-appears notes on rows that predate a wording change.
        for slot_key, notes in expected_media_slots():
            MediaAsset.objects.filter(slot_key=slot_key).exclude(notes=notes).update(notes=notes)

        filled, kept = attach_seed_images()
        total = MediaAsset.objects.count()
        empty = MediaAsset.objects.filter(image="").count()
        self.stdout.write(
            f"  media: {total} slots ({created} new, {pruned} pruned) — "
            f"{filled} seeded, {kept} already had an image, {empty} still empty"
        )

    def seed_payments(self):
        """Subscription tiers (the platform's revenue) + the legacy zero fee policy."""
        from apps.payments.models import FeePolicy, SubscriptionPlan

        if not FeePolicy.objects.filter(is_active=True).exists():
            FeePolicy.objects.create(
                percent=0, is_active=True, note="Platform takes 0% of a project"
            )

        data = load_optional("subscription_plans") or {}
        for group in (SubscriptionPlan.Group.STANDARD, SubscriptionPlan.Group.PRICING_PAGE):
            for row in data.get(group, []):
                SubscriptionPlan.objects.update_or_create(
                    group=group,
                    key=row["key"],
                    defaults={
                        "name": row["name"],
                        "tagline": row.get("tagline", ""),
                        "price_monthly": row["price_monthly"],
                        "price_yearly": row.get("price_yearly"),
                        "per_unit": row.get("per_unit", ""),
                        "project_ceiling": row.get("project_ceiling", ""),
                        "metro_coverage": row.get("metro_coverage", ""),
                        "pursuit_limit": row.get("pursuit_limit", ""),
                        "fits": row.get("fits", ""),
                        "points": row.get("points", []),
                        "cta_label": row.get("cta_label", ""),
                        "is_recommended": row.get("is_recommended", False),
                        "gateway_price_id": row.get("gateway_price_id", ""),
                        "sort_order": row.get("sort", 0),
                    },
                )
        self.stdout.write(
            f"  payments: {SubscriptionPlan.objects.count()} plans, "
            f"fee policy {FeePolicy.current_percent()}%"
        )
