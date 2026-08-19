"""Re-encode stored images that predate `ProcessedImageField`.

See `apps.core.reprocess` for why this exists. Safe to run repeatedly: once a file is
under the threshold it is never looked at again.
"""

from django.core.management.base import BaseCommand

from apps.core.reprocess import OVERSIZE_BYTES, reprocess_oversized


class Command(BaseCommand):
    help = "Re-encode stored images larger than --threshold bytes through the upload pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--threshold", type=int, default=OVERSIZE_BYTES)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        shrunk, saved = reprocess_oversized(
            threshold=options["threshold"], dry_run=options["dry_run"]
        )
        verb = "would shrink" if options["dry_run"] else "shrank"
        self.stdout.write(f"{verb} {shrunk} image(s), saving {saved / 1_048_576:.1f} MB")
