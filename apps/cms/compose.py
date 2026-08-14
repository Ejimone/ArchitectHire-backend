"""Composition of the per-page content payload.

`compose_page` is the one place that decides what a marketing page's JSON looks like.
`PageContentView` serves it to the public site; the Studio serves it to its canvas with
`include_unpublished=True` so an editor sees pending work. Both must produce the *same
shape*, because the Studio renders the site's own components against it — a field the
Studio composes differently is a field whose preview lies.
"""

from django.db import connection

from apps.core.models import PublishableModel

from .models import (
    FAQ,
    CaseCard,
    CopyBlock,
    CredentialBadge,
    EstimateTeaserOption,
    FeatureMatrixRow,
    HeroCarouselSlide,
    MediaAsset,
    PageSEO,
    Persona,
    Principle,
    SiteSettings,
    Stat,
    Step,
    Testimonial,
    TrustLogo,
    UseCase,
    ValueProp,
)
from .serializers import (
    CaseCardSerializer,
    CredentialBadgeSerializer,
    EstimateTeaserOptionSerializer,
    FAQSerializer,
    FeatureMatrixRowSerializer,
    HeroCarouselSlideSerializer,
    MediaAssetSerializer,
    PageSEOSerializer,
    PersonaSerializer,
    PrincipleSerializer,
    SiteSettingsSerializer,
    StatSerializer,
    StepSerializer,
    TestimonialSerializer,
    TrustLogoSerializer,
    UseCaseSerializer,
    ValuePropSerializer,
)

# (payload key, model, serializer). The single source of truth for the scoped block
# collections: the public endpoint, the Studio composer, the seed command and the cache
# tag tests all read this list rather than keeping their own copy.
BLOCK_REGISTRY = [
    ("faqs", FAQ, FAQSerializer),
    ("stats", Stat, StatSerializer),
    ("steps", Step, StepSerializer),
    ("testimonials", Testimonial, TestimonialSerializer),
    ("value_props", ValueProp, ValuePropSerializer),
    ("trust_logos", TrustLogo, TrustLogoSerializer),
    ("credential_badges", CredentialBadge, CredentialBadgeSerializer),
    ("use_cases", UseCase, UseCaseSerializer),
    ("personas", Persona, PersonaSerializer),
    ("principles", Principle, PrincipleSerializer),
    ("carousel", HeroCarouselSlide, HeroCarouselSlideSerializer),
    ("case_cards", CaseCard, CaseCardSerializer),
    ("estimate_teaser", EstimateTeaserOption, EstimateTeaserOptionSerializer),
    ("feature_matrix", FeatureMatrixRow, FeatureMatrixRowSerializer),
]

BLOCK_MODELS = {model._meta.label_lower: model for _name, model, _s in BLOCK_REGISTRY}
BLOCK_KEY_BY_LABEL = {model._meta.label_lower: name for name, model, _s in BLOCK_REGISTRY}
BLOCK_SERIALIZERS = {model._meta.label_lower: s for _name, model, s in BLOCK_REGISTRY}


def populated_collections(page_key, *, include_unpublished=False) -> set[str]:
    """Which of the 14 block collections this page has rows in — in one round trip.

    A page uses three or four block types; querying all fourteen meant ten wasted round
    trips per rebuild, which is ~2s when the app and database are not co-located. One
    `UNION ALL` of `EXISTS` probes answers the same question once, and every probe is an
    index-only lookup on `(scope)`.

    Table names come from `_meta.db_table` and the status literal from the model, so the
    only user-supplied value is `page_key`, which is bound as a parameter.
    """
    probes = []
    params = []
    for name, model, _serializer in BLOCK_REGISTRY:
        table = connection.ops.quote_name(model._meta.db_table)
        condition = "scope = %s"
        row_params = [name, page_key]
        if not include_unpublished:
            condition += " AND status = %s"
            row_params.append(PublishableModel.Status.PUBLISHED)
        # `%s::text` rather than a bare placeholder: with no FROM clause to infer a type
        # from, Postgres rejects an untyped parameter in the select list.
        probes.append(
            f"SELECT %s::text AS collection WHERE EXISTS (SELECT 1 FROM {table} WHERE {condition})"
        )
        params += row_params

    with connection.cursor() as cursor:
        cursor.execute(" UNION ALL ".join(probes), params)
        return {row[0] for row in cursor.fetchall()}


def compose_page(page_key, request, *, include_unpublished=False):
    """The composed payload for one scope key.

    `include_unpublished` folds draft-status blocks in alongside published ones, which is
    what the Studio canvas wants and what the public endpoint must never do. Scope
    validity is the caller's business — this builds whatever key it is handed.
    """
    settings_obj = SiteSettings.get_solo()
    seo = PageSEO.objects.filter(page_key=page_key).first()

    present = populated_collections(page_key, include_unpublished=include_unpublished)
    blocks = {}
    for name, model, serializer_class in BLOCK_REGISTRY:
        if name not in present:
            continue
        queryset = model.objects.filter(scope=page_key)
        if not include_unpublished:
            queryset = queryset.published()
        data = serializer_class(queryset, many=True, context={"request": request}).data
        if data:
            blocks[name] = data

    media = MediaAsset.objects.filter(slot_key__startswith=f"{page_key}:").exclude(image="")
    # `many=True` builds one serializer for the whole queryset; the old per-asset
    # construction rebuilt the field tree for every row.
    media_map = {
        entry["slot_key"]: entry
        for entry in MediaAssetSerializer(media, many=True, context={"request": request}).data
    }

    copy = {
        block.key: {"text": block.text, "href": block.href}
        for block in CopyBlock.objects.filter(scope=page_key)
    }

    return {
        "page": page_key,
        "seo": PageSEOSerializer(seo, context={"request": request}).data if seo else None,
        "settings": SiteSettingsSerializer(settings_obj, context={"request": request}).data,
        "copy": copy,
        "blocks": blocks,
        "media": media_map,
    }
