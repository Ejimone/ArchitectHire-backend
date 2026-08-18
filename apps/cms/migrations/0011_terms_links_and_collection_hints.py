"""Content repairs the seed cannot be trusted to deliver.

`seed --all` is a floor, not a sync (see the seed command): a row that exists is left
alone, so a fix to seeded content never reaches a database that has already been seeded —
which is every environment but a fresh test one. Content corrections therefore ship as
data migrations.

1. Footer and pro-onboarding "Terms of Service" links pointed at `/privacy#terms`, an
   anchor the privacy page never had (owner decision 2026-08-11: the terms live at
   `/terms`, and the seed patch that created that page never repointed the links).
2. The three inspiration "curated collections" cards get the design's placeholder label
   for their (still empty) cover image. Without it the site repeated the card title inside
   the image box, on top of the card's own headline.
"""

from django.db import migrations

TERMS_LINKS = {
    ("chrome", "footer_terms"),
    ("pro", "arch_terms_1"),
    ("pro", "exp_terms_1"),
    ("pro", "terms_2"),
    ("pro", "terms_3"),
}

COLLECTION_HINTS = {
    "Backyard ADUs under 700 sq ft": "ADU collection cover",
    "Kitchens that open up": "Kitchen collection cover",
    "Additions that match the original": "Addition collection cover",
}


def forwards(apps, schema_editor):
    CopyBlock = apps.get_model("cms", "CopyBlock")
    Persona = apps.get_model("cms", "Persona")

    for scope, key in TERMS_LINKS:
        CopyBlock.objects.filter(scope=scope, key=key, href="/privacy#terms").update(href="/terms")
    # Anything else that still carries the dead anchor — a patch row, an owner edit that
    # copied it — gets the same repair.
    CopyBlock.objects.filter(href="/privacy#terms").update(href="/terms")

    for title, hint in COLLECTION_HINTS.items():
        Persona.objects.filter(scope="inspiration", group="collections", title=title).update(
            image_hint=hint
        )

    # Historical models fire no signals, so purge the content cache by hand. Best effort:
    # a migration must not fail because Redis is unreachable at deploy time.
    try:
        from apps.core.cache import bump_content_version

        bump_content_version(())
    except Exception:  # depends on the deploy environment; migrations are outside coverage
        pass


class Migration(migrations.Migration):
    dependencies = [("cms", "0010_mediaasset_focal_persona_image_hint")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
