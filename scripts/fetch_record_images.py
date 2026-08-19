#!/usr/bin/env python
"""Fill the *record* images from Pexels, once, into committed seed files.

The companion to `fetch_seed_images.py`, which does the same job for named `MediaAsset`
slots. Record images live as a column on a content row — a case card's photo, a
testimonial's portrait, a case study's hero — and had no seeded floor at all, so those
sections rendered as crosshatch placeholders on a fresh install.

Two differences from the slot fetcher, both about size:

* Photographs are drawn from **pools by subject**, and one file serves several rows: forty
  testimonial portraits come from twenty faces, not forty. Rows are assigned round-robin
  within a pool in a stable order, so the three portraits on one city page are three
  different people.
* The manifest is keyed on the **natural key** of the row (`cms.casecard|landing|<title>`),
  never its primary key, so the same file lands on the same row on any machine.

Like the slot fetcher this is a laptop tool: it writes `seeds/records/`, those files are
committed, and production never calls Pexels.

Usage:
    uv run python scripts/fetch_record_images.py            # only rows with no file yet
    uv run python scripts/fetch_record_images.py --refresh  # re-fetch every pool
    uv run python scripts/fetch_record_images.py --only cms.testimonial
"""

import argparse
import json
import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402

from apps.cms.record_media import MANIFEST, SEED_DIR, expected_record_images  # noqa: E402
from apps.core.images import process_image  # noqa: E402
from scripts.fetch_seed_images import (  # noqa: E402  — the Pexels client, shared
    FACE_EDGE,
    WIDE_EDGE,
    _download,
    _search,
    _session_key,
    say,
)

#: pool → (search, orientation, how many distinct photographs, long edge).
#: The counts are chosen so neighbours on a page differ without the repository carrying a
#: separate file per row: 62 portraits are drawn from 20 faces, 23 ADU shots from 10.
POOLS = {
    "portrait": ("professional headshot portrait person", "portrait", 20, FACE_EDGE),
    "exterior": ("modern house exterior architecture", "landscape", 10, WIDE_EDGE),
    "adu": ("small backyard studio cabin exterior", "landscape", 10, WIDE_EDGE),
    "kitchen": ("modern kitchen interior renovation", "landscape", 8, WIDE_EDGE),
    "commercial": ("modern restaurant interior design", "landscape", 8, WIDE_EDGE),
    "addition": ("house extension construction exterior", "landscape", 6, WIDE_EDGE),
    "drafting": ("architect blueprint technical drawing desk", "landscape", 6, WIDE_EDGE),
    "render": ("architectural 3d render building visualization", "landscape", 6, WIDE_EDGE),
    "living": ("modern living room interior daylight", "landscape", 5, WIDE_EDGE),
    "city": ("city neighbourhood street aerial", "landscape", 3, WIDE_EDGE),
    "bathroom": ("modern bathroom interior design", "landscape", 2, WIDE_EDGE),
    "site": ("architect construction site meeting plans", "landscape", 2, WIDE_EDGE),
}


def pool_file(pool: str, index: int) -> str:
    return f"{pool}-{index + 1}.webp"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Re-fetch pools already on disk.")
    parser.add_argument("--only", default="", help="Only rows whose key starts with this.")
    args = parser.parse_args()

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    #: Assign every row to a pool slot first, so we know how many photographs each pool
    #: actually needs before spending a single request.
    rows = sorted(
        (key, spec.pool(obj)) for key, spec, obj in expected_record_images(only_empty=False)
    )
    if args.only:
        rows = [row for row in rows if row[0].startswith(args.only)]

    seen: dict[str, int] = {}
    assignment: dict[str, tuple[str, int]] = {}
    for key, pool in rows:
        position = seen.get(pool, 0)
        seen[pool] = position + 1
        size = POOLS[pool][2]
        assignment[key] = (pool, position % size)

    needed = {pool: min(count, POOLS[pool][2]) for pool, count in seen.items()}
    say(f"{len(rows)} rows across {len(needed)} pools")

    fetched = failed = 0
    credits: dict[str, dict] = {}
    session = _session_key()
    for pool, count in sorted(needed.items()):
        query, orientation, _size, edge = POOLS[pool]
        missing = [
            index
            for index in range(count)
            if args.refresh or not (SEED_DIR / pool_file(pool, index)).exists()
        ]
        if missing:
            photos = _search(session, query, orientation, max(missing) + 1)
            if not photos:
                say(f"  ! no results for {query!r}")
                failed += len(missing)
                continue
            say(f"  {query!r} ({orientation}) -> {len(missing)} photo(s) for pool {pool!r}")
            for index in missing:
                photo = photos[index % len(photos)]
                raw = _download(photo["src"]["large2x"])
                if raw is None:
                    say(f"    ! download failed: {pool}-{index + 1}")
                    failed += 1
                    continue
                processed = process_image(
                    SimpleUploadedFile(f"{pool}-{index}.jpg", raw), max_edge=edge, to_format="WEBP"
                )
                processed.seek(0)
                (SEED_DIR / pool_file(pool, index)).write_bytes(processed.read())
                credits[pool_file(pool, index)] = {
                    "query": query,
                    "credit": f"Photo by {photo['photographer']} on Pexels",
                    "photographer_url": photo["photographer_url"],
                    "source_url": photo["url"],
                    "alt": (photo.get("alt") or "").strip(),
                }
                fetched += 1

    for key, (pool, index) in assignment.items():
        name = pool_file(pool, index)
        if not (SEED_DIR / name).exists():
            continue
        # A pool photograph fetched this run brings its credit; one already on disk keeps
        # whatever the manifest recorded when it was first written.
        previous = {k: v for k, v in manifest.get(key, {}).items() if k not in ("file", "pool")}
        manifest[key] = {"file": name, "pool": pool, **credits.get(name, previous)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    say(f"\n{fetched} photographs written, {failed} failed")
    say(f"{len(manifest)} rows mapped -> {SEED_DIR.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
