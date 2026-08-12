"""Coarse version-key cache invalidation for CMS content.

One integer version lives in Redis; any CMS/catalog/jurisdictions write bumps it,
implicitly invalidating every composed-page cache entry. Old keys expire by TTL.
"""

from django.core.cache import cache

CONTENT_VERSION_KEY = "cms:version"
CONTENT_TTL = 60 * 15  # safety TTL regardless of version bumps


def get_content_version() -> int:
    version = cache.get(CONTENT_VERSION_KEY)
    if version is None:
        cache.add(CONTENT_VERSION_KEY, 1, timeout=None)
        return 1
    return version


def bump_content_version() -> None:
    try:
        cache.incr(CONTENT_VERSION_KEY)
    except ValueError:
        cache.add(CONTENT_VERSION_KEY, 2, timeout=None)
    # Tell the frontend to drop its cached pages so admin edits show instantly.
    # Queued, not called inline: this runs inside a post_save signal.
    from apps.core.revalidate import schedule_ping

    schedule_ping()


def page_cache_key(page_key: str) -> str:
    return f"page:{page_key}:v{get_content_version()}"


def content_etag(page_key: str) -> str:
    return f'"{get_content_version()}-{page_key}"'
