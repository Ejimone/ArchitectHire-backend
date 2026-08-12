"""Omnisearch — the command palette's cross-model provider."""

import pytest
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import reverse

from apps.cms.models import FAQ, MediaAsset
from apps.cms.models_editorial import BlogPost
from apps.studio.search import omnisearch

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_superuser(
        email="search-owner@architecthire.test", password="studio-pass-12345"
    )


def _request(user):
    request = RequestFactory().get("/admin/search/")
    request.user = user
    return request


def test_short_terms_return_nothing(owner):
    assert omnisearch(_request(owner), "a") == []
    assert omnisearch(_request(owner), "") == []
    assert omnisearch(_request(owner), None) == []


def test_finds_a_model_row(owner):
    BlogPost.objects.create(title="Permit timelines explained", slug="permit-timelines")

    results = omnisearch(_request(owner), "permit timelines")

    titles = [r.title for r in results]
    assert "Permit timelines explained" in titles


def test_finds_a_page_which_is_not_a_database_row(clean_content, owner):
    results = omnisearch(_request(owner), "careers")

    pages = [r for r in results if r.description.startswith("Page ")]
    assert [p.title for p in pages] == ["Careers"]
    assert pages[0].link == reverse("admin:studio_page_composer", kwargs={"page_key": "careers"})


def test_finds_an_image_slot_by_its_note(clean_content, owner):
    MediaAsset.objects.create(slot_key="about:about-hero", notes="About page hero image")

    results = omnisearch(_request(owner), "about page hero")

    slots = [r for r in results if r.description.startswith("Image slot")]
    assert slots and slots[0].title == "About page hero image"


def test_results_link_to_the_change_form(owner):
    faq = FAQ.objects.create(scope="landing", question="Zoning setbacks", answer="")

    results = omnisearch(_request(owner), "zoning setbacks")

    match = next(r for r in results if r.title == str(faq))
    assert match.link == reverse("admin:cms_faq_change", args=[faq.pk])


def test_hides_models_the_user_cannot_view(clean_content, django_user_model):
    BlogPost.objects.create(title="Permit timelines explained", slug="permit-timelines")
    MediaAsset.objects.create(slot_key="about:about-hero", notes="Permit hero")
    viewer = django_user_model.objects.create_user(
        email="narrow@architecthire.test", password="studio-pass-12345", is_staff=True
    )
    viewer.user_permissions.add(Permission.objects.get(codename="view_blogpost"))

    results = omnisearch(_request(viewer), "permit")

    descriptions = {r.description for r in results}
    assert "Blog post" in descriptions
    assert not any(d.startswith("Image slot") for d in descriptions)


def test_caps_results_per_model(clean_content, owner):
    for index in range(9):
        BlogPost.objects.create(title=f"Permit guide {index}", slug=f"permit-guide-{index}")

    results = omnisearch(_request(owner), "permit guide")

    assert len([r for r in results if r.description == "Blog post"]) == 5


# --- The site-level cache drop ------------------------------------------------


def test_command_palette_finds_a_record_saved_after_an_earlier_search(client, owner):
    """The reason StudioAdminSite overrides `search`.

    Unfold caches palette results for five minutes per (user, term). Searching for
    something that does not exist yet, creating it, then searching again is the exact
    sequence a CMS produces — and with the stock cache the second search would still
    return the empty first result.
    """
    cache.clear()
    client.force_login(owner)
    url = reverse("admin:search")

    first = client.get(url, {"s": "estuary"})
    assert "Estuary House" not in first.content.decode()

    BlogPost.objects.create(title="Estuary House", slug="estuary-house")

    second = client.get(url, {"s": "estuary"})
    assert "Estuary House" in second.content.decode()


def test_search_with_no_term_returns_empty(client, owner):
    client.force_login(owner)

    response = client.get(reverse("admin:search"))

    assert response.status_code == 200
    assert response.content == b""
