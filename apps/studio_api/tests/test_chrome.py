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
