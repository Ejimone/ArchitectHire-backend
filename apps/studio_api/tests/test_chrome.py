"""The chrome read: site-wide rows with ids, which the public endpoints omit."""

import pytest

from apps.cms.models import FooterColumn, FooterLink, NavGroup, NavItem, SiteSettings
from apps.studio_api import drafts as engine

pytestmark = pytest.mark.django_db


class TestChrome:
    def test_requires_a_studio_token(self, api_client):
        assert api_client.get("/api/v1/studio/chrome/").status_code == 401

    def test_rows_carry_ids_and_editable_fields(self, studio_client):
        # Other test modules commit seed content, so rows are looked up by id rather
        # than assumed to be alone in their table.
        group = NavGroup.objects.create(menu="services", heading="Drafting")
        item = NavItem.objects.create(group=group, label="CAD", href="/services/cad-drafting")
        column = FooterColumn.objects.create(heading="Company")
        link = FooterLink.objects.create(column=column, label="About", href="/about")

        body = studio_client.get("/api/v1/studio/chrome/").json()

        def find(label, pk):
            return next(row for row in body["rows"][label] if row["id"] == pk)

        assert find("cms.navgroup", group.pk)["menu"] == "services"
        assert find("cms.navgroup", group.pk)["heading"] == "Drafting"
        # The FK arrives as the parent's pk — how the editor nests items under groups.
        assert find("cms.navitem", item.pk)["group"] == group.pk
        assert find("cms.footercolumn", column.pk)["heading"] == "Company"
        assert find("cms.footerlink", link.pk)["column"] == link.column_id

    def test_the_settings_singleton_is_created_on_first_read(self, studio_client):
        body = studio_client.get("/api/v1/studio/chrome/").json()
        settings_rows = body["rows"]["cms.sitesettings"]
        assert len(settings_rows) == 1
        assert settings_rows[0]["id"] == SiteSettings.get_solo().pk

    def test_staged_chrome_edits_show_in_the_pending_map(self, studio_client, staff_user):
        group = NavGroup.objects.create(menu="services", heading="Old heading")
        engine.stage(
            model_label="cms.navgroup",
            op="update",
            object_id=group.pk,
            payload={"heading": "New heading"},
            user=staff_user,
        )

        body = studio_client.get("/api/v1/studio/chrome/").json()

        assert body["pending"][f"cms.navgroup:{group.pk}"] == "update"
        # Values stay live on purpose: review of a draft's contents happens in the queue.
        row = next(r for r in body["rows"]["cms.navgroup"] if r["id"] == group.pk)
        assert row["heading"] == "Old heading"

    def test_page_scoped_drafts_stay_out_of_the_chrome_pending_map(self, studio_client, staff_user):
        draft = engine.stage(
            model_label="cms.copyblock",
            op="create",
            payload={"scope": "landing", "key": "hero_h1", "text": "New"},
            user=staff_user,
        )
        body = studio_client.get("/api/v1/studio/chrome/").json()
        assert f"cms.copyblock:{draft.canvas_id}" not in body["pending"]


@pytest.mark.django_db
def test_rows_carry_file_urls_for_their_image_fields(studio_client, image_upload):
    from apps.cms.models import NavGroup, NavItem

    group = NavGroup.objects.create(menu="services", heading="Files probe")
    item = NavItem.objects.create(group=group, label="With picture", href="/x")
    item.image.save("nav.png", image_upload, save=True)
    NavItem.objects.create(group=group, label="Without", href="/y")
    body = studio_client.get("/api/v1/studio/chrome/").json()
    rows = {row["label"]: row for row in body["rows"]["cms.navitem"]}
    assert rows["With picture"]["files"]["image"].startswith("http")
    assert rows["Without"]["files"]["image"] is None
    assert "hero_image" in body["rows"]["cms.sitesettings"][0]["files"]


@pytest.mark.django_db
class TestSiteSettingsOnTheCanvas:
    """The one piece of site chrome that travels *inside* a page payload.

    The landing hero is painted from `settings.hero_image`, and site settings are
    deliberately scope-blank because they are site-wide. `overlay()` filtered drafts on
    scope alone, so replacing the hero was accepted, queued and badged as pending — and
    the canvas went on rendering the live value. From the editor's chair the upload
    simply did nothing.
    """

    def _stage(self, studio_client, image_upload):
        settings_row = SiteSettings.get_solo()
        stored = studio_client.post(
            "/api/v1/studio/uploads/",
            {"model_label": "cms.sitesettings", "field": "hero_image", "file": image_upload},
            format="multipart",
        )
        assert stored.status_code == 200, stored.data
        name = stored.json()["name"]
        patched = studio_client.patch(
            f"/api/v1/studio/rows/cms.sitesettings/{settings_row.pk}/",
            {"hero_image": name},
            format="json",
        )
        assert patched.status_code == 200, patched.data
        return settings_row, name

    def test_a_staged_hero_shows_on_the_canvas(self, studio_client, image_upload):
        row, name = self._stage(studio_client, image_upload)

        body = studio_client.get("/api/v1/studio/pages/landing/?mode=draft").json()

        assert body["settings"]["hero_image"], "the draft canvas still shows the live hero"
        assert name.rsplit("/", 1)[-1] in body["settings"]["hero_image"]
        assert body["pending"][f"cms.sitesettings:{row.pk}"] == "update"

    def test_live_mode_keeps_showing_the_published_hero(self, studio_client, image_upload):
        self._stage(studio_client, image_upload)
        published = SiteSettings.get_solo().hero_image.name

        body = studio_client.get("/api/v1/studio/pages/landing/?mode=live").json()

        # A draft must never leak into what the public site is serving.
        hero = body["settings"]["hero_image"]
        assert (hero is None) if not published else published.rsplit("/", 1)[-1] in hero

    def test_settings_reach_every_page_not_just_the_one_that_was_open(
        self, studio_client, image_upload
    ):
        """They are site-wide: the promo banner is on every page, so a pending change
        has to be visible from whichever canvas the editor is standing on."""
        _, name = self._stage(studio_client, image_upload)

        body = studio_client.get("/api/v1/studio/pages/about/?mode=draft").json()

        assert name.rsplit("/", 1)[-1] in body["settings"]["hero_image"]

    def test_publishing_moves_it_to_live(self, studio_client, image_upload):
        _, name = self._stage(studio_client, image_upload)

        assert studio_client.post("/api/v1/studio/publish/").status_code == 200

        body = studio_client.get("/api/v1/studio/pages/landing/?mode=live").json()
        assert name.rsplit("/", 1)[-1] in body["settings"]["hero_image"]

    def test_the_records_api_still_refuses_site_settings(self, studio_client):
        """Why the studio panel must read the page payload rather than `/records/`:
        site settings are chrome, not a collection, and this answers 400."""
        row = SiteSettings.get_solo()
        response = studio_client.get(f"/api/v1/studio/records/cms.sitesettings/{row.pk}/")
        assert response.status_code == 400
