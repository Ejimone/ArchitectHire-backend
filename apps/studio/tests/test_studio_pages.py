"""The five custom Studio screens."""

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.cms.models import FAQ, CopyBlock, MediaAsset, PageSEO
from apps.studio import pages as page_registry
from apps.studio.publishing import draft_groups, draft_total, publishable_models

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_superuser(
        email="owner@architecthire.test", password="studio-pass-12345"
    )


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


@pytest.fixture
def landing_faq():
    return FAQ.objects.create(
        scope="landing", question="How long do permits take?", answer="It depends.", sort_order=1
    )


# --- Command Center ----------------------------------------------------------


def test_the_admin_index_uses_the_studio_template_not_unfolds(owner_client):
    """`TEMPLATES["DIRS"]` is empty and `APP_DIRS` is on, so `admin/index.html`
    resolves by INSTALLED_APPS order. If `apps.studio` ever falls behind `unfold`,
    Unfold's stock app list silently wins and the Command Center disappears —
    with every other Studio page still working, so nothing else would fail.

    Asserted on the template's origin rather than on page text: "Command Center" also
    appears in the sidebar nav, so a content check passes even when the dashboard is
    gone. That false positive is exactly how this shipped broken the first time.
    """
    response = owner_client.get(reverse("admin:index"))

    origins = [t.origin.name for t in response.templates if t.name == "admin/index.html"]

    assert origins, "admin/index.html was not rendered"
    assert origins[0].endswith("apps/studio/templates/admin/index.html"), (
        f"Unfold shadowed the Command Center; admin/index.html came from {origins[0]}"
    )


def test_command_center_renders_health_and_metrics(clean_content, owner_client, landing_faq):
    response = owner_client.get(reverse("admin:index"))
    body = response.content.decode()

    assert response.status_code == 200
    # Markup unique to the Command Center template — absent from Unfold's app list.
    assert "studio-kicker" in body
    assert "Content health" in body
    assert "Marketplace" in body
    assert "Recent activity" in body

    assert {card["label"] for card in response.context["studio_health"]} == {
        "Empty image slots",
        "Pages missing SEO",
        "Waiting in draft",
        "Empty copy blocks",
    }
    assert len(response.context["studio_metrics"]) == 6
    assert len(response.context["studio_actions"]) == 4


def test_command_center_activity_feed_lists_admin_edits(owner_client, owner, landing_faq):
    # Editing through the admin is what writes a LogEntry.
    owner_client.post(
        reverse("admin:cms_faq_change", args=[landing_faq.pk]),
        {
            "scope": "landing",
            "group": "",
            "question": "How long do permits take?",
            "answer": "Usually six weeks.",
            "status": "published",
            "sort_order": 1,
        },
    )

    response = owner_client.get(reverse("admin:index"))

    activity = response.context["studio_activity"]
    assert activity, "expected the edit to appear in the activity feed"
    assert activity[0]["object"] == str(landing_faq)
    assert activity[0]["user"] == owner.email


# --- Page Composer -----------------------------------------------------------


def test_page_list_groups_pages_into_sections(owner_client):
    response = owner_client.get(reverse("admin:studio_pages"))

    assert response.status_code == 200
    assert "Marketing" in response.context["sections"]
    assert response.context["total_pages"] >= len(page_registry.static_pages())


def test_page_list_search_filters(owner_client):
    response = owner_client.get(reverse("admin:studio_pages"), {"q": "careers"})

    keys = [ref.key for refs in response.context["sections"].values() for ref in refs]
    assert keys == ["careers"]


def test_page_composer_gathers_everything_on_one_page(clean_content, owner_client, landing_faq):
    CopyBlock.objects.create(scope="landing", key="hero.title", text="Design your home")
    PageSEO.objects.create(
        page_key="landing", title="ArchitectHire", description="Find an architect"
    )
    MediaAsset.objects.create(slot_key="landing:hero-arch", notes="Hero portrait")

    url = reverse("admin:studio_page_composer", kwargs={"page_key": "landing"})
    response = owner_client.get(url)

    assert response.status_code == 200
    assert response.context["seo"].title == "ArchitectHire"
    assert [b.key for b in response.context["copy_blocks"]] == ["hero.title"]
    assert [a.slot_key for a in response.context["media"]] == ["landing:hero-arch"]

    stacks = {stack["name"]: stack for stack in response.context["block_stacks"]}
    assert "faqs" in stacks
    assert stacks["faqs"]["count"] == 1
    assert stacks["faqs"]["rows"][0]["label"] == str(landing_faq)


def test_page_composer_builds_a_frontend_preview_url(owner_client, settings):
    settings.FRONTEND_URL = "https://architecthire.com/"

    response = owner_client.get(reverse("admin:studio_page_composer", kwargs={"page_key": "about"}))

    assert response.context["preview_url"] == "https://architecthire.com/about"


def test_page_composer_omits_preview_for_pages_with_no_public_url(owner_client):
    response = owner_client.get(
        reverse("admin:studio_page_composer", kwargs={"page_key": "chrome"})
    )

    assert response.context["preview_url"] is None


def test_page_composer_rejects_an_invalid_scope(owner_client):
    response = owner_client.get(
        reverse("admin:studio_page_composer", kwargs={"page_key": "not-a-real-page"})
    )

    assert response.status_code == 404


def test_page_composer_handles_a_dynamic_scope_with_no_row(owner_client):
    """A city page whose City row was deleted still has to render its blocks."""
    url = reverse("admin:studio_page_composer", kwargs={"page_key": "city:nowhere"})

    response = owner_client.get(url)

    assert response.status_code == 200
    assert response.context["page_ref"].section == "Other"


# --- Media Library -----------------------------------------------------------


def test_media_library_groups_slots_and_counts_fill_state(clean_content, owner_client):
    MediaAsset.objects.create(slot_key="about:about-hero", notes="About hero")
    MediaAsset.objects.create(slot_key="landing:hero-arch", notes="Landing hero")

    response = owner_client.get(reverse("admin:studio_media"))

    assert response.status_code == 200
    assert response.context["total_slots"] == 2
    assert response.context["empty_slots"] == 2
    assert set(response.context["groups"]) == {"about", "landing"}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "About"}, 1),
        ({"page_key": "landing"}, 1),
        ({"state": "empty"}, 2),
        ({"state": "filled"}, 0),
    ],
)
def test_media_library_filters(clean_content, owner_client, params, expected):
    MediaAsset.objects.create(slot_key="about:about-hero", notes="About hero")
    MediaAsset.objects.create(slot_key="landing:hero-arch", notes="Landing hero")

    response = owner_client.get(reverse("admin:studio_media"), params)

    assert response.context["shown"] == expected


def test_media_upload_stores_the_image_and_returns_json(clean_content, owner_client, image_upload):
    asset = MediaAsset.objects.create(slot_key="landing:hero-arch", notes="Landing hero")

    response = owner_client.post(
        reverse("admin:studio_media_upload"),
        {"slot_key": asset.slot_key, "image": image_upload, "alt_text": "A house"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["slot_key"] == "landing:hero-arch"
    assert payload["alt_text"] == "A house"

    asset.refresh_from_db()
    assert asset.image
    assert asset.alt_text == "A house"


def test_media_upload_rejects_a_missing_slot(owner_client, image_upload):
    response = owner_client.post(
        reverse("admin:studio_media_upload"),
        {"slot_key": "landing:does-not-exist", "image": image_upload},
    )

    assert response.status_code == 404


def test_media_upload_requires_both_fields(owner_client):
    response = owner_client.post(reverse("admin:studio_media_upload"), {})

    assert response.status_code == 400


def test_media_upload_rejects_get(owner_client):
    response = owner_client.get(reverse("admin:studio_media_upload"))

    assert response.status_code == 405


def test_media_upload_requires_change_permission(
    clean_content, client, django_user_model, image_upload
):
    asset = MediaAsset.objects.create(slot_key="landing:hero-arch", notes="Landing hero")
    viewer = django_user_model.objects.create_user(
        email="viewer@architecthire.test", password="studio-pass-12345", is_staff=True
    )
    viewer.user_permissions.add(Permission.objects.get(codename="view_mediaasset"))
    client.force_login(viewer)

    response = client.post(
        reverse("admin:studio_media_upload"),
        {"slot_key": asset.slot_key, "image": image_upload},
    )

    assert response.status_code == 403


def test_media_sync_creates_the_static_slot_inventory(clean_content, owner_client):
    assert MediaAsset.objects.count() == 0

    response = owner_client.post(reverse("admin:studio_media_sync"), follow=True)

    assert response.status_code == 200
    assert MediaAsset.objects.filter(slot_key="landing:hero-arch").exists()


def test_media_sync_requires_change_permission(client, django_user_model):
    viewer = django_user_model.objects.create_user(
        email="viewer2@architecthire.test", password="studio-pass-12345", is_staff=True
    )
    client.force_login(viewer)

    response = client.post(reverse("admin:studio_media_sync"))

    assert response.status_code == 403


# --- Publish Queue -----------------------------------------------------------


def test_publish_queue_lists_only_models_with_drafts(clean_content, owner_client):
    FAQ.objects.create(scope="landing", question="Draft one", answer="", status="draft")
    FAQ.objects.create(scope="about", question="Live one", answer="", status="published")

    response = owner_client.get(reverse("admin:studio_queue"))

    assert response.status_code == 200
    assert response.context["total"] == 1
    labels = {group.label for group in response.context["groups"]}
    assert labels == {"Faqs"}


def test_publish_queue_is_empty_when_nothing_is_drafted(clean_content, owner_client):
    response = owner_client.get(reverse("admin:studio_queue"))

    assert response.context["total"] == 0
    assert "Nothing waiting" in response.content.decode()


def test_publish_everything_flips_all_drafts(clean_content, owner_client):
    FAQ.objects.create(scope="landing", question="One", answer="", status="draft")
    FAQ.objects.create(scope="about", question="Two", answer="", status="draft")

    response = owner_client.post(reverse("admin:studio_queue_publish"), follow=True)

    assert response.status_code == 200
    assert draft_total() == 0
    assert all(faq.published_at for faq in FAQ.objects.all())


def test_publish_one_model_leaves_others_alone(clean_content, owner_client):
    from apps.cms.models import Stat

    FAQ.objects.create(scope="landing", question="One", answer="", status="draft")
    Stat.objects.create(scope="landing", value="12", label="Cities", status="draft")

    owner_client.post(reverse("admin:studio_queue_publish"), {"model": "cms.faq"}, follow=True)

    assert FAQ.objects.filter(status="draft").count() == 0
    assert Stat.objects.filter(status="draft").count() == 1


def test_publish_one_page_only_touches_that_scope(clean_content, owner_client):
    FAQ.objects.create(scope="landing", question="On landing", answer="", status="draft")
    FAQ.objects.create(scope="about", question="On about", answer="", status="draft")

    response = owner_client.post(
        reverse("admin:studio_queue_publish"), {"scope": "landing"}, follow=True
    )

    assert response.status_code == 200
    assert FAQ.objects.get(scope="landing").status == "published"
    assert FAQ.objects.get(scope="about").status == "draft"


def test_publish_skips_models_the_user_cannot_change(client, django_user_model):
    FAQ.objects.create(scope="landing", question="One", answer="", status="draft")
    viewer = django_user_model.objects.create_user(
        email="viewer3@architecthire.test", password="studio-pass-12345", is_staff=True
    )
    client.force_login(viewer)

    client.post(reverse("admin:studio_queue_publish"), follow=True)

    assert FAQ.objects.filter(status="draft").count() == 1


# --- Registry ----------------------------------------------------------------


def test_publishable_models_finds_the_scoped_blocks():
    labels = {model._meta.label_lower for model in publishable_models()}

    assert "cms.faq" in labels
    assert "cms.blogpost" in labels
    assert "cms.mediaasset" not in labels  # not publishable


def test_draft_groups_can_include_empty_models(clean_content):
    with_empty = draft_groups(include_empty=True)
    without_empty = draft_groups()

    assert len(with_empty) == len(publishable_models())
    assert without_empty == []


# --- Access ------------------------------------------------------------------


@pytest.mark.parametrize("route", ["studio_pages", "studio_media", "studio_queue"])
def test_studio_pages_are_staff_only(client, django_user_model, route):
    outsider = django_user_model.objects.create_user(
        email="outsider@architecthire.test", password="studio-pass-12345"
    )
    client.force_login(outsider)

    response = client.get(reverse(f"admin:{route}"))

    assert response.status_code == 302
    assert "/admin/login/" in response.url
