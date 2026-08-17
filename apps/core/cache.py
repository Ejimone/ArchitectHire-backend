"""Version-key cache invalidation for CMS content.

Every cached endpoint is identified by a *slug* — `landing`, `city:oakland`, `_nav`,
`_catalog` — and each slug carries its own version counter in Redis. A write bumps only
the slugs it actually affects, so editing the landing page leaves the other 112 page
payloads warm.

There is also one global `epoch`, mixed into every key. Writes that genuinely reach the
whole site (site settings, which every page embeds) bump that instead, and so does
anything whose tags we cannot map to a slug — over-purging costs one rebuild, while
under-purging serves stale content until an unrelated write happens to clear it.

Rebuilding a page payload costs 18 database round trips, which is ~4s when the app and
the database are not co-located. That is why the granularity matters: under a single
global counter, one typo fix in a footer link made every page on the site pay it.
"""

from django.core.cache import cache
from django.db import transaction

CONTENT_EPOCH_KEY = "cms:epoch"
CONTENT_TTL = 60 * 15  # safety TTL regardless of version bumps

# Tag prefix → cache slug, for the tags that name exactly one cached endpoint. Kept in
# step with `apps.core.tags` (which produces them) and the `cache_slug` attributes on
# the CachedContentView subclasses (which consume them).
_SLUG_BY_TAG = {
    "cms:nav": "_nav",
    "cms:footer": "_footer",
    "cms:settings": "_settings",
    "cms:catalog": "_catalog",
    "cms:catalog:plans": "_plans",
    "cms:jurisdictions": "_states",
    # The media endpoint caches one payload per `?prefix=`, but versions them all off
    # this single slug — see `MediaSlotsView.get_version_slug`. Without it the slug
    # `_media:<prefix>` matched no tag, so its counter never moved past 1: an uploaded
    # image stayed invisible for the full TTL, and because the ETag is built from the
    # same frozen version, any client sending If-None-Match was told 304 against the
    # empty body indefinitely.
    "cms:media": "_media",
}
_PAGE_TAG_PREFIX = "cms:page:"


def _counter(key: str) -> int:
    version = cache.get(key)
    if version is None:
        cache.add(key, 1, timeout=None)
        # `add` loses a race with a concurrent writer, so re-read rather than assume 1.
        return cache.get(key) or 1
    return version


def _increment(key: str) -> None:
    try:
        cache.incr(key)
    except ValueError:  # the key expired; seed it past whatever readers already saw
        cache.add(key, 2, timeout=None)


def get_content_epoch() -> int:
    """The global counter. Bumping it invalidates every cached payload at once."""
    return _counter(CONTENT_EPOCH_KEY)


def get_content_version(slug: str | None = None) -> tuple[int, int]:
    """`(epoch, slug version)` — the pair a cache key and an ETag are built from.

    Returned together, and passed back into `page_cache_key`/`content_etag` by callers
    that need to compare before and after a build: reading them twice could straddle a
    write and key the lookup and the store to different versions.
    """
    epoch = get_content_epoch()
    if slug is None:
        return (epoch, 0)
    return (epoch, _counter(f"cms:v:{slug}"))


def slugs_for_tags(tags) -> set[str] | None:
    """The cache slugs a set of frontend tags invalidates, or None for "everything".

    None is the deliberate answer for the catch-all and for anything unrecognised: a tag
    this module has not been taught about must widen the purge, never narrow it.
    """
    tags = set(tags or ())
    if not tags:
        return None
    slugs = set()
    for tag in tags:
        if tag.startswith(_PAGE_TAG_PREFIX):
            slugs.add(tag[len(_PAGE_TAG_PREFIX) :])
        elif tag in _SLUG_BY_TAG:
            slugs.add(_SLUG_BY_TAG[tag])
        else:
            return None
    return slugs


def bump_content_version(tags=()) -> None:
    """Invalidate the cached payloads a write affects, once now and once after commit.

    The admin wraps every save in a transaction, so this fires while the row is still
    invisible to other connections. Bumping only before the commit lets a read landing
    in that window rebuild a page from the pre-commit snapshot and store it under the
    *new* version for the full TTL; bumping only after leaves the same window open
    between COMMIT and the callback. So: bump now, to stop anyone serving the old key,
    and again on commit, to orphan whatever a mid-transaction read managed to cache.

    `tags` names the frontend cache entries this write invalidates (see
    :mod:`apps.core.tags`); empty means "the whole site".
    """
    slugs = slugs_for_tags(tags)

    def _bump():
        if slugs is None:
            _increment(CONTENT_EPOCH_KEY)
            return
        for slug in slugs:
            _increment(f"cms:v:{slug}")

    _bump()

    def _after_commit():
        _bump()
        # Imported here: this module is loaded from signal wiring at app startup.
        from apps.core.revalidate import schedule_ping

        schedule_ping(tags)

    transaction.on_commit(_after_commit)


def page_cache_key(slug: str, version: tuple[int, int] | None = None) -> str:
    """Cache key for a cached endpoint's payload.

    A caller that compares the version either side of a build passes the one it read,
    so a single request can never key its lookup and its store to two versions.
    """
    epoch, slug_version = version if version is not None else get_content_version(slug)
    return f"page:{slug}:v{epoch}.{slug_version}"


def content_etag(slug: str, version: tuple[int, int] | None = None) -> str:
    """As with `page_cache_key`, a caller that already read the version passes it, so the
    ETag names the version the body was actually built at rather than a later one."""
    epoch, slug_version = version if version is not None else get_content_version(slug)
    return f'"{epoch}.{slug_version}-{slug}"'
