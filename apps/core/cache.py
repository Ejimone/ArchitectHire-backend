"""Coarse version-key cache invalidation for CMS content.

One integer version lives in Redis; any CMS/catalog/jurisdictions write bumps it,
implicitly invalidating every composed-page cache entry. Old keys expire by TTL.
"""

from django.core.cache import cache
from django.db import transaction

CONTENT_VERSION_KEY = "cms:version"
CONTENT_TTL = 60 * 15  # safety TTL regardless of version bumps


def get_content_version() -> int:
    version = cache.get(CONTENT_VERSION_KEY)
    if version is None:
        cache.add(CONTENT_VERSION_KEY, 1, timeout=None)
        return 1
    return version


def _increment() -> None:
    try:
        cache.incr(CONTENT_VERSION_KEY)
    except ValueError:  # the key expired; seed it past whatever readers already saw
        cache.add(CONTENT_VERSION_KEY, 2, timeout=None)


def bump_content_version(tags=()) -> None:
    """Invalidate cached page payloads, once now and once after the commit.

    The admin wraps every save in a transaction, so this fires while the row is still
    invisible to other connections. Bumping only before the commit lets a read landing
    in that window rebuild a page from the pre-commit snapshot and store it under the
    *new* version for the full TTL; bumping only after leaves the same window open
    between COMMIT and the callback. So: bump now, to stop anyone serving the old key,
    and again on commit, to orphan whatever a mid-transaction read managed to cache.

    `tags` names the frontend cache entries this write invalidates (see
    :mod:`apps.core.tags`); empty means "the whole site".
    """
    _increment()

    def _after_commit():
        _increment()
        # Imported here: this module is loaded from signal wiring at app startup.
        from apps.core.revalidate import schedule_ping

        schedule_ping(tags)

    transaction.on_commit(_after_commit)


def page_cache_key(page_key: str, version: int | None = None) -> str:
    """Cache key for a composed page payload.

    A caller that compares the version either side of a build passes the one it read,
    so a single request can never key its lookup and its store to two versions.
    """
    if version is None:
        version = get_content_version()
    return f"page:{page_key}:v{version}"


def content_etag(page_key: str, version: int | None = None) -> str:
    """As with `page_cache_key`, a caller that already read the version passes it, so the
    ETag names the version the body was actually built at rather than a later one."""
    if version is None:
        version = get_content_version()
    return f'"{version}-{page_key}"'
