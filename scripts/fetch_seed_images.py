#!/usr/bin/env python
"""Fill the image-slot inventory from Pexels, once, into committed seed files.

**Why the images are committed rather than fetched at deploy time.** The site must never
render as a wireframe again — that is the whole point of this exercise — and a site that
depends on a third-party API being up, and on an API key existing in the environment, to
have any imagery at all is a site that can go back to being a wireframe. So this script is
a *development tool*: it runs on a laptop, writes `seeds/media/`, and those files are
committed. Production never calls Pexels and needs no key.

Pexels images are free for commercial use and attribution is not required, but every
photographer is recorded in the manifest and on the MediaAsset row regardless — an
unattributed image is one nobody can later check the provenance of.

These are a *floor*, not a final answer. Every one is meant to be replaced by the agency's
own photography through the studio; seeding them just means the replacement is an
improvement rather than a prerequisite.

Usage:
    uv run python scripts/fetch_seed_images.py            # only slots with no file yet
    uv run python scripts/fetch_seed_images.py --refresh  # re-fetch everything
    uv run python scripts/fetch_seed_images.py --only city:austin
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import django
import requests

#: `requests`, not urllib, for two reasons this script hit in order: Python on macOS does
#: not use the system keychain, so urllib has no CA bundle and every HTTPS call fails with
#: CERTIFICATE_VERIFY_FAILED; and once that was fixed with certifi, Pexels answered 403 to
#: urllib for a request curl made successfully. requests behaves like curl.
SESSION = requests.Session()

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

from apps.catalog.models import ProjectType  # noqa: E402
from apps.cms.models import MediaAsset  # noqa: E402
from apps.core.images import process_image  # noqa: E402
from apps.jurisdictions.models import City  # noqa: E402


def say(message):
    """Progress output. One `noqa` here beats one on every call site."""
    print(message)  # noqa: T201


OUT_DIR = BASE_DIR / "seeds" / "media"
MANIFEST = OUT_DIR / "manifest.json"
API = "https://api.pexels.com/v1/search"

#: Wide imagery keeps more pixels than a portrait thumbnail needs. These are seed
#: defaults, not the owner's hero photography, so they are deliberately smaller than the
#: 2560px cap `ProcessedImageField` applies to real uploads.
WIDE_EDGE = 1600
FACE_EDGE = 700


def _q(text, orientation="landscape", edge=WIDE_EDGE):
    return {"query": text, "orientation": orientation, "edge": edge}


#: Static slots, keyed exactly. A group shares one search and takes a different photo from
#: the results per slot, so six "specialist portrait" slots do not become the same face.
STATIC_GROUPS = {
    # --- marketing heroes -----------------------------------------------------
    "services-landing:svl-hero": _q("modern architecture building exterior"),
    "about:about-hero": _q("architects working in a design studio"),
    "about:about-why": _q("architect reviewing blueprints at a desk"),
    "architect-landing:alp-hero": _q("architect working on building plans"),
    "architect-landing:alp-control": _q("architect desk with laptop and drawings"),
    "for-experts:fx-hero": _q("engineer reviewing technical drawings"),
    "for-experts:fx-control": _q("designer working at computer workstation"),
    "cad-drafting:cad-hero": _q("architectural blueprint technical drawing"),
    "3d-visualization:viz-hero": _q("3d architectural rendering interior"),
    "professional-tools:pt-hero": _q("dark modern office workspace at night"),
    # --- portraits ------------------------------------------------------------
    "landing:hero-arch": _q("professional headshot smiling", "square", FACE_EDGE),
    "about:about-hero-face": _q("professional portrait architect", "square", FACE_EDGE),
    "blog:blog-feat-face": _q("professional woman portrait", "square", FACE_EDGE),
    "case-studies:cs-arch": _q("architect professional portrait", "square", FACE_EDGE),
    "account:me": _q("friendly professional portrait", "square", FACE_EDGE),
    "account:avatar": _q("professional headshot person", "square", FACE_EDGE),
    "pro:me": _q("architect portrait professional", "square", FACE_EDGE),
    "pro:avatar": _q("professional headshot man", "square", FACE_EDGE),
    "pro:review": _q("happy client portrait", "square", FACE_EDGE),
    "engagement:architect": _q("architect headshot", "square", FACE_EDGE),
    # --- quiz style tiles -----------------------------------------------------
    "get-started:style-modern": _q("modern minimalist house exterior"),
    "get-started:style-contemporary": _q("contemporary house architecture"),
    "get-started:style-farmhouse": _q("modern farmhouse exterior"),
    "get-started:style-craftsman": _q("craftsman style house porch"),
    "get-started:style-mediterranean": _q("mediterranean villa exterior"),
    "get-started:style-traditional": _q("traditional family house exterior"),
    "get-started:style-open": _q("open plan living room interior"),
    # --- quiz reference photos ------------------------------------------------
    "get-started:quiz-beds-ref": _q("bedroom interior design"),
    "get-started:quiz-baths-ref": _q("modern bathroom interior"),
    "get-started:quiz-stories-ref": _q("two storey house exterior"),
    # --- signed-in app fallbacks ---------------------------------------------
    "engagement:upnext": _q("house under construction framing"),
    "engagement:video": _q("video call meeting laptop"),
    "engagement:video-self": _q("person on video call", "square", FACE_EDGE),
}

#: Slots deliberately left empty. These render product UI, and a stock photo of a generic
#: "dashboard" reads as a stock photo of a generic dashboard — worse than the crosshatch
#: placeholder, because it looks like a claim about the product that is not true. They are
#: filled from real screenshots of the app instead (see `--from-screenshots`).
SKIP = {
    "professional-tools:ft-booking",
    "professional-tools:ft-clients",
    "professional-tools:ft-juris",
    "professional-tools:ft-pipeline",
    "professional-tools:ft-profile",
    "professional-tools:ft-proposal",
    "professional-tools:ft-reply",
    "pro:portfolio-0",
    "pro:portfolio-1",
    "pro:portfolio-2",
    "pro:portfolio-3",
}

#: Search terms per project type, so a "Restaurant build-out" gallery is restaurants and
#: not another generic house. Keyed on ProjectType.slug.
PROJECT_QUERIES = {
    "backyard-adu": "small modern guest house backyard",
    "garage-conversion": "converted garage living space",
    "home-addition": "house extension addition exterior",
    "kitchen-and-bath": "modern kitchen renovation interior",
    "new-custom-home": "custom modern home exterior",
    "whole-home-renovation": "renovated home interior living room",
    "commercial-ti": "modern office interior fit out",
    "restaurant-build-out": "restaurant interior design",
    "change-of-use": "converted warehouse building interior",
}


def _session_key():
    from django.conf import settings

    key = getattr(settings, "PEXELS_API_KEY", "") or os.environ.get("PEXELS_API_KEY", "")
    if not key:
        # Read straight from .env — this is a dev tool and the key is deliberately not a
        # Django setting, because production must never need it.
        for line in (BASE_DIR / ".env").read_text().splitlines():
            if line.startswith("PEXELS_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        sys.exit("PEXELS_API_KEY not found in .env or the environment.")
    return key


def _search(key, query, orientation, count):
    params = {
        "query": query,
        "orientation": orientation,
        # Always ask for a few, even for a single slot: a group takes a different photo
        # per slot, and a one-result search leaves no room to vary.
        "per_page": max(count, 3),
        "size": "large",
    }
    for attempt in range(3):
        try:
            response = SESSION.get(API, params=params, headers={"Authorization": key}, timeout=30)
            response.raise_for_status()
            return response.json()["photos"]
        except requests.RequestException as exc:
            if attempt == 2:
                say(f"    ! search failed for {query!r}: {exc}")
                return []
            time.sleep(2 * (attempt + 1))
    return []


def _download(url):
    for attempt in range(3):
        try:
            response = SESSION.get(url, timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == 2:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def _filename(slot_key):
    return slot_key.replace(":", "__") + ".webp"


def build_groups():
    """`[(query, orientation, edge, [slot_key, ...]), ...]` covering every empty slot.

    Slots are grouped by search so one request serves a whole gallery, and each slot in a
    group takes a different photo from the results.
    """
    groups = {}

    def add(query, orientation, edge, slot_key):
        groups.setdefault((query, orientation, edge), []).append(slot_key)

    for slot_key, spec in STATIC_GROUPS.items():
        add(spec["query"], spec["orientation"], spec["edge"], slot_key)

    for city in City.objects.all().order_by("slug"):
        place = f"{city.name} {city.state.name}"
        add(f"{place} skyline city", "landscape", WIDE_EDGE, f"cities:city-{city.slug}")
        add(f"{place} architecture street", "landscape", WIDE_EDGE, f"city:{city.slug}:hero")
        for i in range(1, 4):
            add(f"{place} home exterior", "landscape", WIDE_EDGE, f"city:{city.slug}:work-{i}")

    for project in ProjectType.objects.all().order_by("slug"):
        query = PROJECT_QUERIES.get(project.slug, f"{project.name} architecture")
        if project.slot_id:
            add(query, "landscape", WIDE_EDGE, f"projects:{project.slot_id}")
        for i in range(1, 5):
            add(query, "landscape", WIDE_EDGE, f"project-type:{project.slug}:proj-hero{i}")
            add(query, "landscape", WIDE_EDGE, f"project-type:{project.slug}:p-g{i}")

    # Service-page galleries and specialist portraits.
    for i in range(1, 7):
        add(
            "3d architectural visualization render",
            "landscape",
            WIDE_EDGE,
            f"3d-visualization:viz-d{i}",
        )
        add("architect professional portrait", "square", FACE_EDGE, f"3d-visualization:viz-s{i}")
    for i in range(1, 6):
        add("interior 3d rendering modern", "landscape", WIDE_EDGE, f"3d-visualization:viz-g{i}")
        add("architectural floor plan drawing", "landscape", WIDE_EDGE, f"cad-drafting:cad-g{i}")
    for i in range(1, 4):
        add("draftsman professional portrait", "square", FACE_EDGE, f"cad-drafting:cad-s{i}")

    return [(q, o, e, slots) for (q, o, e), slots in groups.items()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch slots that already have a file."
    )
    parser.add_argument("--only", default="", help="Only slots whose key starts with this prefix.")
    parser.add_argument(
        "--pick",
        type=int,
        default=None,
        help=(
            "Take the Nth search result instead of the default. The top hit for a query is "
            "often not the best image for the slot — 'modern minimalist house exterior' "
            "returned a house with a FOR SALE sign — so this is how a specific slot gets "
            "re-rolled without changing anyone else's. Use with --only and --refresh."
        ),
    )
    parser.add_argument(
        "--query",
        default="",
        help="Override the search text for the selected slots. Use with --only and --refresh.",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    key = _session_key()

    known = set(MediaAsset.objects.values_list("slot_key", flat=True))
    groups = build_groups()

    wanted, skipped_unknown = [], []
    for query, orientation, edge, slots in groups:
        keep = []
        for slot in slots:
            if slot in SKIP or (args.only and not slot.startswith(args.only)):
                continue
            if slot not in known:
                skipped_unknown.append(slot)
                continue
            if not args.refresh and (OUT_DIR / _filename(slot)).exists():
                continue
            keep.append(slot)
        if keep:
            wanted.append((query, orientation, edge, keep))

    total = sum(len(s) for _, _, _, s in wanted)
    say(f"{total} slots to fetch across {len(wanted)} searches")
    if skipped_unknown:
        say(f"  ({len(skipped_unknown)} mapped slots are not in the inventory — ignored)")
    if not total:
        return

    done = failed = 0
    for query, orientation, edge, slots in wanted:
        if args.query:
            query = args.query
        # With --pick we need results at least that deep, plus a few to choose from.
        want = len(slots) if args.pick is None else args.pick + 1
        photos = _search(key, query, orientation, max(want, 15 if args.pick is not None else 0))
        if not photos:
            failed += len(slots)
            continue
        say(f"  {query!r} ({orientation}) -> {len(slots)} slot(s)")
        for index, slot in enumerate(slots):
            position = args.pick if args.pick is not None else index
            photo = photos[position % len(photos)]
            raw = _download(photo["src"]["large2x"])
            if raw is None:
                say(f"    ! download failed: {slot}")
                failed += 1
                continue
            processed = process_image(
                SimpleUploadedFile(f"{slot}.jpg", raw), max_edge=edge, to_format="WEBP"
            )
            processed.seek(0)
            (OUT_DIR / _filename(slot)).write_bytes(processed.read())
            manifest[slot] = {
                "file": _filename(slot),
                "query": query,
                "credit": f"Photo by {photo['photographer']} on Pexels",
                "photographer_url": photo["photographer_url"],
                "source_url": photo["url"],
                "alt": (photo.get("alt") or "").strip(),
            }
            done += 1
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    say(f"\n{done} written, {failed} failed -> {OUT_DIR.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
