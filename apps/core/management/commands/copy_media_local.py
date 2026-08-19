"""Copy every file the database references out of object storage onto local disk.

The first half of taking media off DigitalOcean Spaces. It is deliberately its own step:
run it while the site is still *serving* from the bucket, as many times as you like, and
nothing changes for anyone. Only when the copy is complete and verified does
`MEDIA_BACKEND=local` get flipped, and that flip is a one-line change with an obvious
rollback.

Names, not URLs, are what the database stores — `cms/case-cards/adu-3.webp` — and the
public URL is built from `MEDIA_URL` at render time. So a byte-for-byte copy under the
same names is the entire migration: no rows change, no links rewrite, and rolling back is
flipping the variable the other way.

Private files (deliverables, credential scans, message attachments) are copied to their
own root, outside `MEDIA_ROOT`, because nothing may ever serve them as static files.
"""

from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import models


def referenced_files():
    """`(name, storage, private)` for every non-empty file column in the database.

    Deduplicated: one photograph shared by forty testimonial rows is one copy.
    """
    seen: set[tuple[str, bool]] = set()
    for model in django_apps.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, models.FileField):
                continue
            private = field.storage is not default_storage
            rows = model._default_manager.exclude(**{field.name: ""}).values_list(
                field.name, flat=True
            )
            for name in rows.iterator():
                if not name or (name, private) in seen:
                    continue
                seen.add((name, private))
                yield name, field.storage, private


class Command(BaseCommand):
    help = "Copy every file the database references from the current storage onto local disk."

    def add_arguments(self, parser):
        parser.add_argument("--dest", help="Public media root (default: MEDIA_ROOT).")
        parser.add_argument(
            "--private-dest", help="Private media root (default: PRIVATE_MEDIA_ROOT)."
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would be copied.")

    def handle(self, *args, **options):
        public_root = Path(options["dest"] or settings.MEDIA_ROOT)
        private_root = Path(
            options["private_dest"]
            or getattr(settings, "PRIVATE_MEDIA_ROOT", None)
            or public_root.parent / "media-private"
        )
        dry_run = options["dry_run"]

        copied = skipped = missing = 0
        for name, storage, private in referenced_files():
            target = (private_root if private else public_root) / name
            try:
                size = storage.size(name)
            except Exception as exc:  # noqa: BLE001 — any storage's "it is not there"
                # A row pointing at a deleted object is a pre-existing problem, not a
                # reason to abandon the migration half-done. Name it and move on.
                self.stderr.write(f"  missing: {name} ({exc.__class__.__name__})")
                missing += 1
                continue

            if target.exists() and target.stat().st_size == size:
                skipped += 1
                continue
            if dry_run:
                copied += 1
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with storage.open(name) as source:
                # A temporary name then a rename: an interrupted copy must never leave a
                # truncated file that the next run mistakes for a complete one.
                staging = target.with_name(f".{target.name}.part")
                staging.write_bytes(source.read())
                staging.replace(target)
            copied += 1

        verb = "would copy" if dry_run else "copied"
        self.stdout.write(
            f"{verb} {copied}, already present {skipped}, missing from storage {missing}"
        )
        self.stdout.write(f"  public  → {public_root}")
        self.stdout.write(f"  private → {private_root}")
