"""Reconcile the MediaAsset slot inventory with what the site actually renders.

`seed --domain media` does this too, but seeding rewrites content along the way. This
command touches nothing but the slot rows, so it is the safe thing to run on production
after a deploy that adds a city, a project type, or a gallery row.

Rows holding an uploaded image are never deleted — only empty rows whose slot no longer
exists are pruned.
"""

from django.core.management.base import BaseCommand

from apps.cms.models import MediaAsset
from apps.cms.slots import expected_media_slots, sync_media_slots


class Command(BaseCommand):
    help = "Create MediaAsset rows for every expected image slot; prune empty orphans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            expected = dict(expected_media_slots())
            existing = set(MediaAsset.objects.values_list("slot_key", flat=True))
            missing = sorted(set(expected) - existing)
            orphaned = sorted(
                MediaAsset.objects.filter(image="")
                .exclude(slot_key__in=expected.keys())
                .values_list("slot_key", flat=True)
            )
            for key in missing:
                self.stdout.write(f"  + {key}")
            for key in orphaned:
                self.stdout.write(f"  - {key}")
            self.stdout.write(
                self.style.WARNING(
                    f"dry run: {len(missing)} to create, {len(orphaned)} to prune, "
                    f"{len(expected)} slots expected"
                )
            )
            return

        created, pruned = sync_media_slots()
        total = MediaAsset.objects.count()
        filled = MediaAsset.objects.exclude(image="").count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} slots ({created} new, {pruned} pruned) — "
                f"{filled} filled, {total - filled} awaiting an upload"
            )
        )
