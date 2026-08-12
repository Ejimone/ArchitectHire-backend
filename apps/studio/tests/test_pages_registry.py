"""Page-key resolution edge cases."""

import pytest

from apps.studio import pages as page_registry

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("page_key", "expected"),
    [
        ("landing", "/"),
        ("about", "/about"),
        ("chrome", None),
        ("city:oakland", "/cities/oakland"),
        ("state:CA", "/jurisdictions/ca"),
        ("blog-post:permit-timelines", "/guides/permit-timelines"),
    ],
)
def test_route_for_known_keys(page_key, expected):
    assert page_registry.route_for(page_key) == expected


@pytest.mark.parametrize("page_key", ["blog-post:", "unknown-prefix:thing", "nonsense"])
def test_route_for_returns_none_when_there_is_no_public_url(page_key):
    assert page_registry.route_for(page_key) is None


def test_a_new_static_key_still_reaches_the_composer(monkeypatch):
    """Adding a page key to apps.core.scopes must never make it invisible here.

    SECTIONS is a hand-curated grouping; anything not placed in it falls through to
    an "Other" section rather than silently disappearing.
    """
    monkeypatch.setattr(page_registry, "STATIC_PAGE_KEYS", ["landing", "brand-new-page"])

    refs = {ref.key: ref for ref in page_registry.static_pages()}

    assert refs["brand-new-page"].section == "Other"
    assert refs["brand-new-page"].label == "Brand new page"


def test_dynamic_pages_skip_rows_with_no_slug(clean_content):
    """A slugless row has no URL, so it cannot be a page."""
    from apps.catalog.models import Service, ServiceCategory

    category = ServiceCategory.objects.create(name="Drafting", slug="drafting")
    Service.objects.create(category=category, name="No slug", slug="")
    Service.objects.create(category=category, name="Has slug", slug="has-slug")

    keys = {ref.key for ref in page_registry.dynamic_pages()}

    assert "service:has-slug" in keys
    assert "service:" not in keys


def test_find_page_returns_none_for_an_unknown_key():
    assert page_registry.find_page("no-such-page") is None
