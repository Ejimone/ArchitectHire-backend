"""Stock photography for images that live on a content row.

`MediaAsset` slots have had a seeded floor since Stage 3a; the *record* images — a case
card's photo, a testimonial's portrait, a case study's hero — never did, so a fresh
install renders those sections as crosshatch placeholders. This module is the equivalent
floor for them.

Three properties matter, and each one is a decision:

* **Keyed on natural keys, never primary keys.** A row's pk differs between a laptop, the
  production database and any future restore; `(scope, title)` does not. The seeder
  already addresses every one of these models that way.
* **Never overwrites.** `seed` runs on deploys. A row whose image the owner has set is
  finished — the whole point of the studio is that their photograph wins.
* **Written with `obj.save()`**, never `.update()` or `bulk_create()`, so `post_save`
  fires, the cache version bumps and the live site is purged. A seeded image nobody can
  see until an unrelated write happens would be worse than no image.

Files are shared: one photograph can serve several rows (a portrait pool spread across
forty testimonials), and the first row that needs a file uploads it while the rest are
pointed at the same storage name. That keeps both the repository and the object store
small, and is exactly what "reuse from library" does in the studio.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files import File

SEED_DIR = Path(settings.BASE_DIR) / "seeds" / "records"
MANIFEST = SEED_DIR / "manifest.json"


@dataclass(frozen=True)
class RecordImageSpec:
    """One model whose image column gets a seeded floor."""

    label: str
    field: str
    #: Fields that identify a row independently of its pk.
    key_fields: tuple[str, ...]
    #: Which pool a row's picture comes from — the subject, not the file.
    pool: Callable[[object], str]
    #: Rows worth seeding at all. Personas exist on pages that render no portrait, and
    #: seeding those would cost bytes for something nobody sees.
    renders: Callable[[object], bool] = lambda obj: True

    @property
    def model(self):
        from django.apps import apps as django_apps

        return django_apps.get_model(self.label)


def _slug_pool(text: str, default: str = "exterior") -> str:
    """Map a slug or title to a subject pool by the words people actually use."""
    words = text.lower()
    for needle, pool in (
        ("adu", "adu"),
        ("garage", "adu"),
        ("kitchen", "kitchen"),
        ("bath", "bathroom"),
        ("restaurant", "commercial"),
        ("retail", "commercial"),
        ("commercial", "commercial"),
        ("change-of-use", "commercial"),
        ("change of use", "commercial"),
        ("addition", "addition"),
        ("extension", "addition"),
        ("renovation", "living"),
        ("living", "living"),
        ("custom home", "exterior"),
        ("permit", "drafting"),
        ("cost", "drafting"),
        ("hire", "site"),
    ):
        if needle in words:
            return pool
    return default


#: Scopes whose cards are people rather than places, and scopes that are renders.
_PORTRAIT_CARD_SCOPES = {"cad-drafting"}
_RENDER_CARD_SCOPES = {"3d-visualization"}

#: Personas render a portrait on exactly these scopes; elsewhere the row is a text block
#: (service variants, tool descriptions) and its image column is never drawn.
_PERSONA_IMAGE_SCOPES = {"about", "inspiration", "3d-visualization"}

_CAROUSEL_POOLS = {
    "landing": "exterior",
    "services": "drafting",
    "projects": "exterior",
    "cities": "city",
    "cad-drafting": "drafting",
    "3d-visualization": "render",
}

SPECS: list[RecordImageSpec] = [
    RecordImageSpec(
        label="cms.casecard",
        field="image",
        key_fields=("scope", "title"),
        pool=lambda obj: (
            "portrait"
            if obj.scope in _PORTRAIT_CARD_SCOPES
            else "render"
            if obj.scope in _RENDER_CARD_SCOPES
            else _slug_pool(f"{obj.scope} {obj.title}")
        ),
    ),
    RecordImageSpec(
        label="cms.testimonial",
        field="photo",
        key_fields=("scope", "name"),
        pool=lambda obj: "portrait",
    ),
    RecordImageSpec(
        label="cms.persona",
        field="image",
        key_fields=("scope", "title"),
        pool=lambda obj: "portrait" if obj.scope != "inspiration" else _slug_pool(obj.title),
        renders=lambda obj: obj.scope in _PERSONA_IMAGE_SCOPES,
    ),
    RecordImageSpec(
        label="cms.herocarouselslide",
        field="image",
        key_fields=("scope", "caption"),
        pool=lambda obj: _CAROUSEL_POOLS.get(obj.scope, "exterior"),
    ),
    RecordImageSpec(
        label="cms.inspirationitem",
        field="image",
        key_fields=("title",),
        pool=lambda obj: _slug_pool(f"{obj.tag} {obj.title}", default="living"),
    ),
    RecordImageSpec(
        label="cms.casestudy",
        field="hero_image",
        key_fields=("slug",),
        pool=lambda obj: _slug_pool(obj.slug),
    ),
    RecordImageSpec(
        label="cms.casestudyimage",
        field="image",
        key_fields=("case_study__slug", "sort_order"),
        pool=lambda obj: _slug_pool(obj.case_study.slug),
    ),
    RecordImageSpec(
        label="cms.blogpost",
        field="hero_image",
        key_fields=("slug",),
        pool=lambda obj: _slug_pool(obj.slug, default="site"),
    ),
    RecordImageSpec(
        label="cms.author",
        field="photo",
        key_fields=("name",),
        pool=lambda obj: "portrait",
    ),
    RecordImageSpec(
        label="cms.blogcontentblock",
        field="image",
        key_fields=("post__slug", "sort_order"),
        pool=lambda obj: _slug_pool(obj.post.slug, default="site"),
        renders=lambda obj: obj.kind == "image",
    ),
]

SPEC_BY_LABEL = {spec.label: spec for spec in SPECS}


def _value(obj, path: str):
    """`case_study__slug` → `obj.case_study.slug`, so a child can be keyed by its parent."""
    for part in path.split("__"):
        obj = getattr(obj, part, "")
    return obj


def _key_for(spec: RecordImageSpec, obj) -> str:
    parts = [str(_value(obj, name) or "") for name in spec.key_fields]
    return "|".join([spec.label, *parts])


def expected_record_images(only_empty: bool = True):
    """`(key, spec, obj)` for every row that should carry a seeded photograph."""
    for spec in SPECS:
        queryset = spec.model._default_manager.all()
        if only_empty:
            queryset = queryset.filter(**{spec.field: ""})
        for obj in queryset:
            if not spec.renders(obj):
                continue
            yield _key_for(spec, obj), spec, obj


def attach_seed_record_images(*, overwrite: bool = False) -> tuple[int, int]:
    """Fill empty record images from `seeds/records/`. Returns `(filled, skipped)`.

    Skips any row that already has an image unless `overwrite` is asked for explicitly:
    once the owner has uploaded their own photograph, a later `seed --all` must not put
    the stock one back.
    """
    if not MANIFEST.exists():
        return (0, 0)

    manifest = json.loads(MANIFEST.read_text())
    filled = skipped = 0
    #: filename → the storage name its first upload landed on, so rows sharing a
    #: photograph share the file rather than uploading it again.
    stored: dict[str, str] = {}

    # Every candidate row, not just the empty ones: a row the owner has already filled is
    # counted as skipped rather than silently absent, so `seed` can report honestly how
    # much of the site is still stock photography.
    for key, spec, obj in expected_record_images(only_empty=False):
        entry = manifest.get(key)
        if entry is None:
            continue
        if getattr(obj, spec.field) and not overwrite:
            skipped += 1
            continue
        source = SEED_DIR / entry["file"]
        if not source.exists():
            continue

        field = getattr(obj, spec.field)
        if entry["file"] in stored:
            setattr(obj, spec.field, stored[entry["file"]])
        else:
            with source.open("rb") as handle:
                field.save(entry["file"], File(handle), save=False)
            stored[entry["file"]] = getattr(obj, spec.field).name
        # Never `.update()`: post_save is what bumps the content version and purges the
        # frontend, so a bulk write would leave the site serving the placeholder.
        obj.save()
        filled += 1

    return (filled, skipped)
