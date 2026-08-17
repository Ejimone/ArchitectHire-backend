"""The site's image-slot inventory.

Every ``<ImgSlot>`` placeholder on the frontend reads a named slot from the
composed page endpoint (``page.media["<scope>:<slot>"]``). This module lists
those slots — static ones verbatim, per-record ones computed from the DB —
so ``manage.py seed --domain media`` can pre-create one ``MediaAsset`` row per
slot. The owner then just opens Django admin → CMS → Media assets and uploads
into the row; no slot names to memorize.

Per-user slots (chat avatars, matched-architect photos keyed by DB ids) are
intentionally absent: they render from live account data, not admin uploads.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.files import File

from apps.catalog.models import ProjectType
from apps.cms.models import CaseCard, HeroCarouselSlide, MediaAsset, Persona, Testimonial
from apps.jurisdictions.models import City

# Service-detail pages whose galleries are keyed off DB rows rather than a fixed list.
# Each entry is (scope, slot-prefix, model, label) — the page renders
# ``media[f"{scope}:{prefix}{i + 1}"]`` for each row, so the inventory has to count the
# rows to know how many slots exist. Without these the slots were unreachable twice
# over: they never appeared in the media library, and `sync_media_slots` pruned any that
# something else created, because pruning is driven by this very inventory.
_DERIVED_GALLERIES = [
    ("cad-drafting", "cad-g", HeroCarouselSlide, "CAD Drafting — work gallery tile"),
    ("cad-drafting", "cad-s", CaseCard, "CAD Drafting — specialist portrait"),
    ("3d-visualization", "viz-d", CaseCard, "3D Visualization — deliverable card"),
    ("3d-visualization", "viz-g", HeroCarouselSlide, "3D Visualization — work gallery tile"),
    ("3d-visualization", "viz-s", Persona, "3D Visualization — specialist portrait"),
]

STATIC_SLOTS = [
    # Marketing pages
    ("landing:hero-arch", "Home — round portrait in the white review card over the hero"),
    ("services-landing:svl-hero", "Services landing — hero image"),
    ("about:about-hero", "About — hero image"),
    ("about:about-hero-face", "About — small round portrait on the hero card"),
    ("about:about-why", "About — 'why we exist' section image"),
    ("architect-landing:alp-hero", "For Architects — hero image"),
    ("architect-landing:alp-control", "For Architects — 'stay in control' section image"),
    ("for-experts:fx-hero", "For Experts — hero image"),
    ("for-experts:fx-control", "For Experts — 'stay in control' section image"),
    ("cad-drafting:cad-hero", "CAD Drafting service — hero image"),
    ("3d-visualization:viz-hero", "3D Visualization service — hero image"),
    ("blog:blog-feat-face", "Guides — featured-post author portrait"),
    ("case-studies:cs-arch", "Case study pages — architect portrait on the results panel"),
    # Professional Tools feature rows
    ("professional-tools:pt-hero", "Professional Tools — dark hero image"),
    ("professional-tools:ft-clients", "Professional Tools row 1 — matched clients screenshot"),
    ("professional-tools:ft-profile", "Professional Tools row 2 — public profile screenshot"),
    ("professional-tools:ft-reply", "Professional Tools row 3 — instant reply screenshot"),
    ("professional-tools:ft-juris", "Professional Tools row 4 — jurisdiction lookup screenshot"),
    ("professional-tools:ft-booking", "Professional Tools row 5 — booking calendar screenshot"),
    ("professional-tools:ft-proposal", "Professional Tools row 6 — proposal draft screenshot"),
    ("professional-tools:ft-pipeline", "Professional Tools row 7 — pipeline board screenshot"),
    # Get-started quiz
    ("get-started:style-modern", "Quiz — 'Modern' style tile"),
    ("get-started:style-contemporary", "Quiz — 'Contemporary' style tile"),
    ("get-started:style-farmhouse", "Quiz — 'Farmhouse' style tile"),
    ("get-started:style-craftsman", "Quiz — 'Craftsman' style tile"),
    ("get-started:style-mediterranean", "Quiz — 'Mediterranean' style tile"),
    ("get-started:style-traditional", "Quiz — 'Traditional' style tile"),
    ("get-started:style-open", "Quiz — 'Not sure yet' style tile"),
    ("get-started:quiz-beds-ref", "Quiz — reference photo beside the bedrooms step"),
    ("get-started:quiz-baths-ref", "Quiz — reference photo beside the bathrooms step"),
    ("get-started:quiz-stories-ref", "Quiz — reference photo beside the stories step"),
    # Signed-in app fallbacks
    ("account:me", "Client account — profile photo"),
    ("account:avatar", "Client account — small header avatar"),
    ("pro:me", "Pro dashboard — profile photo"),
    ("pro:avatar", "Pro onboarding — avatar"),
    ("pro:review", "Pro dashboard — review card photo"),
    ("pro:portfolio-0", "Pro onboarding — portfolio slot 1 fallback"),
    ("pro:portfolio-1", "Pro onboarding — portfolio slot 2 fallback"),
    ("pro:portfolio-2", "Pro onboarding — portfolio slot 3 fallback"),
    ("pro:portfolio-3", "Pro onboarding — portfolio slot 4 fallback"),
    ("engagement:architect", "Engagement room — architect avatar"),
    ("engagement:video", "Engagement room — video-call still"),
    ("engagement:video-self", "Engagement room — self-view thumbnail"),
    ("engagement:upnext", "Engagement room — 'up next' milestone image"),
]


def expected_media_slots() -> list[tuple[str, str]]:
    """(slot_key, notes) for every owner-fillable image slot, DB-derived included."""
    slots = list(STATIC_SLOTS)

    for city in City.objects.all():
        slots.append((f"cities:city-{city.slug}", f"Cities index — card photo for {city.name}"))
        slots.append((f"city:{city.slug}:hero", f"{city.name} city page — hero image"))
        work = Testimonial.objects.filter(scope=f"city:{city.slug}").count()
        for i in range(work):
            slots.append(
                (f"city:{city.slug}:work-{i + 1}", f"{city.name} city page — work photo {i + 1}")
            )

    for scope, prefix, model, label in _DERIVED_GALLERIES:
        for i in range(model.objects.filter(scope=scope).count()):
            slots.append((f"{scope}:{prefix}{i + 1}", f"{label} {i + 1}"))

    for project in ProjectType.objects.all():
        if project.slot_id:
            slots.append((f"projects:{project.slot_id}", f"Projects index — {project.name} card"))
        gallery = CaseCard.objects.filter(scope=f"project-type:{project.slug}", group="gallery")
        for i in range(gallery.count()):
            slots.append(
                (
                    f"project-type:{project.slug}:proj-hero{i + 1}",
                    f"{project.name} page — hero carousel slide {i + 1}",
                )
            )
            slots.append(
                (
                    f"project-type:{project.slug}:p-g{i + 1}",
                    f"{project.name} page — sample-work carousel slide {i + 1}",
                )
            )

    return slots


#: Committed stock imagery, one file per slot, written by `scripts/fetch_seed_images.py`.
#: Committed rather than fetched at deploy time so that having *any* imagery never depends
#: on a third-party API being reachable or an API key being present — the site rendering as
#: a wireframe is the failure this whole set exists to prevent.
SEED_IMAGE_DIR = Path(settings.BASE_DIR) / "seeds" / "media"
SEED_IMAGE_MANIFEST = SEED_IMAGE_DIR / "manifest.json"


def attach_seed_images(*, overwrite: bool = False) -> tuple[int, int]:
    """Fill empty slots from `seeds/media/`. Returns `(filled, skipped)`.

    Only ever writes into a slot with **no image**, unless `overwrite` is asked for
    explicitly: once the owner has uploaded their own photograph, a later `seed --all`
    must not quietly put the stock placeholder back.
    """
    if not SEED_IMAGE_MANIFEST.exists():
        return (0, 0)

    manifest = json.loads(SEED_IMAGE_MANIFEST.read_text())
    filled = skipped = 0

    for slot_key, entry in manifest.items():
        asset = MediaAsset.objects.filter(slot_key=slot_key).first()
        if asset is None:
            continue
        if asset.image and not overwrite:
            skipped += 1
            continue
        source = SEED_IMAGE_DIR / entry["file"]
        if not source.exists():
            continue

        # `save(save=False)` then an explicit `.save()`, so the row is written once and
        # the post-save signals (cache bump, frontend purge) fire exactly once too.
        asset.image.save(entry["file"], File(source.open("rb")), save=False)
        asset.credit = entry.get("credit", "")
        if not asset.alt_text:
            asset.alt_text = entry.get("alt", "") or asset.notes
        asset.save()
        filled += 1

    return (filled, skipped)


def sync_media_slots() -> tuple[int, int]:
    """Mirror the expected inventory into MediaAsset rows.

    Creates a row (with its where-it-appears note) for every expected slot and
    prunes empty rows whose slot no longer exists (a deleted city, a removed
    gallery card). Rows holding an uploaded image are never deleted. Runs on
    every save/delete of the models the inventory derives from, so the admin
    list is always current without the owner ever typing a slot key.
    """
    expected = dict(expected_media_slots())
    existing = set(MediaAsset.objects.values_list("slot_key", flat=True))
    missing = [
        MediaAsset(slot_key=key, notes=notes)
        for key, notes in expected.items()
        if key not in existing
    ]
    MediaAsset.objects.bulk_create(missing, ignore_conflicts=True)
    pruned, _ = MediaAsset.objects.filter(image="").exclude(slot_key__in=expected.keys()).delete()
    return len(missing), pruned
