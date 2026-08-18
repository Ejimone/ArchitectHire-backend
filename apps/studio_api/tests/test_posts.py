"""Blog authoring: the studio writes posts, the public API only ever sees published ones."""

import pytest

from apps.cms.models_editorial import Author, BlogCategory, BlogContentBlock, BlogPost
from apps.core import cache as cache_module

pytestmark = pytest.mark.django_db

POSTS = "/api/v1/studio/posts/"


def blocks(*texts, kind="paragraph"):
    return [{"kind": kind, "text": text} for text in texts]


def create_post(client, title="A new guide"):
    response = client.post(POSTS, {"title": title}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


class TestAccess:
    def test_anonymous_is_refused(self, api_client):
        assert api_client.get(POSTS).status_code == 401

    def test_a_signed_in_non_staff_user_is_refused(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(POSTS).status_code in (401, 403)

    def test_the_generic_row_api_still_refuses_blog_models(self, studio_client):
        # Blog is written through `views_posts`, never through the draft queue — the
        # queue has no way to point a pending block at a pending post.
        response = studio_client.post("/api/v1/studio/rows/cms.blogpost/", {}, format="json")
        assert response.status_code == 400


class TestCreate:
    def test_a_new_post_starts_as_a_draft(self, studio_client):
        post = create_post(studio_client)
        assert post["status"] == "draft"
        assert post["published_at"] is None
        assert post["slug"] == "a-new-guide"
        assert post["content_blocks"] == []

    def test_a_draft_is_invisible_to_the_public_api(self, studio_client, api_client):
        post = create_post(studio_client)
        listing = api_client.get("/api/v1/content/blog/").json()
        assert post["slug"] not in [row["slug"] for row in listing["results"]]
        assert api_client.get(f"/api/v1/content/blog/{post['slug']}/").status_code == 404

    def test_repeated_titles_get_distinct_addresses(self, studio_client):
        first = create_post(studio_client, "Repeat title check")
        second = create_post(studio_client, "Repeat title check")
        assert first["slug"] == "repeat-title-check"
        assert second["slug"] == "repeat-title-check-2"

    def test_the_list_carries_drafts_and_the_dropdown_contents(self, studio_client):
        # Other modules commit seed content, so taxonomy rows are fetched-or-made and
        # asserted as a subset rather than assumed to be alone in their tables.
        category, _ = BlogCategory.objects.get_or_create(
            slug="test-permits", defaults={"name": "Test permits"}
        )
        author, _ = Author.objects.get_or_create(name="Test Author, AIA")
        post = create_post(studio_client)

        body = studio_client.get(POSTS).json()
        assert post["id"] in [row["id"] for row in body["results"]]
        assert category.name in [c["name"] for c in body["categories"]]
        assert author.name in [a["name"] for a in body["authors"]]
        assert {"paragraph", "h2", "list", "pullquote", "cta", "image"} == {
            kind["value"] for kind in body["kinds"]
        }


class TestBody:
    def test_the_block_array_is_written_whole(self, studio_client):
        post = create_post(studio_client)
        response = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {"content_blocks": blocks("First", "Second", "Third")},
            format="json",
        )
        assert response.status_code == 200, response.json()
        assert [b["text"] for b in response.json()["content_blocks"]] == [
            "First",
            "Second",
            "Third",
        ]

    def test_one_patch_can_reorder_edit_add_and_delete(self, studio_client):
        post = create_post(studio_client)
        written = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {"content_blocks": blocks("one", "two", "three")},
            format="json",
        ).json()["content_blocks"]
        first, second, _third = written

        response = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {
                "content_blocks": [
                    # reordered, retyped, edited, and "three" dropped entirely
                    {"id": second["id"], "kind": "h2", "text": "two edited"},
                    {"id": first["id"], "kind": "paragraph", "text": "one"},
                    {"kind": "pullquote", "text": "brand new", "attribution": "Maya"},
                ]
            },
            format="json",
        )
        body = response.json()["content_blocks"]

        assert [b["text"] for b in body] == ["two edited", "one", "brand new"]
        assert body[0]["kind"] == "h2"
        # An existing block keeps its identity across a reorder, so its uploaded image
        # survives too.
        assert body[0]["id"] == second["id"]
        assert body[1]["id"] == first["id"]
        assert body[2]["attribution"] == "Maya"
        assert BlogContentBlock.objects.filter(post_id=post["id"]).count() == 3

    def test_read_time_is_derived_when_left_blank(self, studio_client):
        post = create_post(studio_client)
        body = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {"content_blocks": blocks(" ".join(["word"] * 600))},
            format="json",
        ).json()
        assert body["read_time"] == "3 min read"

    def test_a_typed_read_time_is_left_alone(self, studio_client):
        post = create_post(studio_client)
        body = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {"read_time": "12 min", "content_blocks": blocks("short")},
            format="json",
        ).json()
        assert body["read_time"] == "12 min"


class TestFields:
    def test_category_and_author_are_set_by_id(self, studio_client):
        category, _ = BlogCategory.objects.get_or_create(
            slug="test-pricing", defaults={"name": "Test pricing"}
        )
        author, _ = Author.objects.get_or_create(name="Test Byline, AIA")
        post = create_post(studio_client)

        body = studio_client.patch(
            f"{POSTS}{post['id']}/",
            {"category": category.pk, "author": author.pk, "dek": "A subtitle"},
            format="json",
        ).json()
        assert body["category"] == category.pk
        assert body["author"] == author.pk
        assert body["dek"] == "A subtitle"

    def test_a_duplicate_address_is_refused_with_a_readable_message(self, studio_client):
        first = create_post(studio_client, "First post")
        second = create_post(studio_client, "Second post")
        response = studio_client.patch(
            f"{POSTS}{second['id']}/", {"slug": first["slug"]}, format="json"
        )
        assert response.status_code == 400
        assert "already uses" in str(response.json()["slug"][0])

    def test_featuring_a_post_unfeatures_the_previous_one(self, studio_client):
        old = BlogPost.objects.create(slug="old", title="Old", is_featured=True)
        post = create_post(studio_client)
        studio_client.patch(f"{POSTS}{post['id']}/", {"is_featured": True}, format="json")

        old.refresh_from_db()
        assert old.is_featured is False
        assert BlogPost.objects.get(pk=post["id"]).is_featured is True

    def test_an_ordinary_save_cannot_publish(self, studio_client):
        post = create_post(studio_client)
        body = studio_client.patch(
            f"{POSTS}{post['id']}/", {"status": "published"}, format="json"
        ).json()
        assert body["status"] == "draft"


class TestPublishing:
    def publishable(self, studio_client):
        post = create_post(studio_client)
        studio_client.patch(
            f"{POSTS}{post['id']}/", {"content_blocks": blocks("Body copy.")}, format="json"
        )
        return post

    def test_publishing_puts_the_post_on_the_site(self, studio_client, api_client):
        post = self.publishable(studio_client)
        response = studio_client.post(f"{POSTS}{post['id']}/publish/", {}, format="json")
        assert response.status_code == 200
        assert response.json()["status"] == "published"
        assert response.json()["published_at"] is not None

        listing = api_client.get("/api/v1/content/blog/").json()
        assert post["slug"] in [row["slug"] for row in listing["results"]]
        detail = api_client.get(f"/api/v1/content/blog/{post['slug']}/")
        assert detail.status_code == 200
        assert detail.json()["content_blocks"][0]["text"] == "Body copy."

    def test_an_empty_post_cannot_be_published(self, studio_client):
        post = create_post(studio_client)
        response = studio_client.post(f"{POSTS}{post['id']}/publish/", {}, format="json")
        assert response.status_code == 400
        assert "body" in response.json()["detail"]

    def test_unpublishing_takes_it_back_off(self, studio_client, api_client):
        post = self.publishable(studio_client)
        studio_client.post(f"{POSTS}{post['id']}/publish/", {}, format="json")
        studio_client.post(f"{POSTS}{post['id']}/unpublish/", {}, format="json")

        assert api_client.get(f"/api/v1/content/blog/{post['slug']}/").status_code == 404
        # The date is the article's, not a record of the button — it survives.
        assert BlogPost.objects.get(pk=post["id"]).published_at is not None

    def test_a_duplicate_is_a_fresh_unfeatured_draft(self, studio_client):
        post = self.publishable(studio_client)
        studio_client.patch(f"{POSTS}{post['id']}/", {"is_featured": True}, format="json")
        studio_client.post(f"{POSTS}{post['id']}/publish/", {}, format="json")

        copy = studio_client.post(f"{POSTS}{post['id']}/duplicate/", {}, format="json").json()
        assert copy["id"] != post["id"]
        assert copy["status"] == "draft"
        assert copy["is_featured"] is False
        assert copy["slug"] != post["slug"]
        assert [b["text"] for b in copy["content_blocks"]] == ["Body copy."]

    def test_deleting_a_post_takes_its_body_with_it(self, studio_client):
        post = self.publishable(studio_client)
        assert studio_client.delete(f"{POSTS}{post['id']}/").status_code == 200
        assert not BlogPost.objects.filter(pk=post["id"]).exists()
        assert not BlogContentBlock.objects.filter(post_id=post["id"]).exists()


class TestTaxonomy:
    def test_a_category_can_be_added_from_the_editor(self, studio_client):
        response = studio_client.post(
            f"{POSTS}categories/", {"name": "Test renovations"}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "test-renovations"
        # Asking twice returns the one that exists rather than a near-duplicate.
        again = studio_client.post(
            f"{POSTS}categories/", {"name": "test renovations"}, format="json"
        )
        assert again.json()["id"] == response.json()["id"]
        assert BlogCategory.objects.filter(name__iexact="test renovations").count() == 1

    def test_an_author_can_be_added_from_the_editor(self, studio_client):
        response = studio_client.post(
            f"{POSTS}authors/",
            {"name": "Test Newcomer, AIA", "role": "Licensed architect"},
            format="json",
        )
        assert response.status_code == 201
        assert Author.objects.filter(name="Test Newcomer, AIA").exists()


class TestCachePurge:
    """A blog write must not throw away every cached page payload on the site."""

    def test_blog_tags_purge_nothing_server_side(self):
        assert cache_module.slugs_for_tags({"cms:blog", "cms:blog:some-post"}) == set()
        assert cache_module.slugs_for_tags({"cms:cases", "cms:case:a-study"}) == set()

    def test_an_unknown_tag_still_widens_to_everything(self):
        assert cache_module.slugs_for_tags({"cms:something-new"}) is None

    def test_a_page_tag_is_unaffected(self):
        assert cache_module.slugs_for_tags({"cms:page:landing"}) == {"landing"}

    def test_saving_a_post_leaves_the_global_epoch_alone(self, studio_client):
        before = cache_module.get_content_epoch()
        post = create_post(studio_client)
        studio_client.patch(
            f"{POSTS}{post['id']}/", {"content_blocks": blocks("Body.")}, format="json"
        )
        studio_client.post(f"{POSTS}{post['id']}/publish/", {}, format="json")
        assert cache_module.get_content_epoch() == before


class TestUploads:
    def test_a_hero_image_can_be_uploaded_for_a_post(self, studio_client, image_upload):
        response = studio_client.post(
            "/api/v1/studio/uploads/",
            {"model_label": "cms.blogpost", "field": "hero_image", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 200, response.json()
        name = response.json()["name"]
        # Normalised on the way in, exactly as the admin would have done it.
        assert name.endswith(".webp")

        post = create_post(studio_client)
        body = studio_client.patch(
            f"{POSTS}{post['id']}/", {"hero_image": name}, format="json"
        ).json()
        assert body["hero_image"] == name
        assert body["hero_image_url"].endswith(name)

    def test_uploads_still_refuse_a_model_that_is_not_on_the_list(
        self, studio_client, image_upload
    ):
        response = studio_client.post(
            "/api/v1/studio/uploads/",
            {"model_label": "accounts.user", "field": "avatar", "file": image_upload},
            format="multipart",
        )
        assert response.status_code == 400


class TestListFiltersAndMissingRows:
    """The branches the first commit left untested: list filters, 404s, publish guards."""

    def test_list_filters_by_search_status_and_category(self, studio_client):
        category, _ = BlogCategory.objects.get_or_create(
            slug="permits-probe", defaults={"name": "Permits probe"}
        )
        draft = create_post(studio_client, title="Draft about permits")
        studio_client.patch(
            f"{POSTS}{draft['id']}/",
            {"category": category.pk, "content_blocks": blocks("Body")},
            format="json",
        )
        published = create_post(studio_client, title="Published guide")
        studio_client.patch(
            f"{POSTS}{published['id']}/", {"content_blocks": blocks("Body")}, format="json"
        )
        assert studio_client.post(f"{POSTS}{published['id']}/publish/").status_code == 200

        titles = lambda query: [  # noqa: E731
            row["title"] for row in studio_client.get(f"{POSTS}?{query}").json()["results"]
        ]
        # The database may carry seeded posts from other test modules, so assert on
        # membership rather than on exact lists.
        assert titles("q=permits") == ["Draft about permits"]
        assert "Published guide" in titles("status=published")
        assert "Draft about permits" not in titles("status=published")
        assert "Draft about permits" in titles("status=draft")
        assert "Published guide" not in titles("status=draft")
        assert {"Draft about permits", "Published guide"} <= set(titles("status=bogus"))
        assert titles("category=permits-probe") == ["Draft about permits"]

    def test_an_untitled_post_gets_a_default_title(self, studio_client):
        response = studio_client.post(POSTS, {"title": "   "}, format="json")
        assert response.status_code == 201
        assert response.json()["title"] == "Untitled post"

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", ""),
            ("patch", ""),
            ("delete", ""),
            ("post", "publish/"),
            ("post", "unpublish/"),
            ("post", "duplicate/"),
        ],
    )
    def test_missing_posts_404(self, studio_client, method, suffix):
        response = getattr(studio_client, method)(f"{POSTS}999999/{suffix}", {}, format="json")
        assert response.status_code == 404

    def test_publish_refuses_a_blank_title_or_an_empty_body(self, studio_client):
        post = create_post(studio_client, title="Has a title")
        assert studio_client.post(f"{POSTS}{post['id']}/publish/").status_code == 400
        BlogPost.objects.filter(pk=post["id"]).update(title="   ")
        studio_client.patch(f"{POSTS}{post['id']}/", {"content_blocks": blocks("x")}, format="json")
        response = studio_client.post(f"{POSTS}{post['id']}/publish/")
        assert response.status_code == 400
        assert "title" in response.json()["detail"]

    def test_publish_keeps_an_existing_date_and_takes_an_explicit_one(self, studio_client):
        post = create_post(studio_client)
        studio_client.patch(f"{POSTS}{post['id']}/", {"content_blocks": blocks("x")}, format="json")
        first = studio_client.post(
            f"{POSTS}{post['id']}/publish/", {"published_at": "2026-01-02T00:00:00Z"}, format="json"
        ).json()
        assert first["published_at"].startswith("2026-01-02")
        studio_client.post(f"{POSTS}{post['id']}/unpublish/")
        again = studio_client.post(f"{POSTS}{post['id']}/publish/").json()
        assert again["published_at"].startswith("2026-01-02")

    def test_taxonomy_creation_edge_cases(self, studio_client):
        assert (
            studio_client.post(f"{POSTS}categories/", {"name": " "}, format="json").status_code
            == 400
        )
        assert (
            studio_client.post(f"{POSTS}authors/", {"name": ""}, format="json").status_code == 400
        )
        BlogCategory.objects.create(name="Design", slug="design")
        existing = studio_client.post(f"{POSTS}categories/", {"name": "design"}, format="json")
        assert existing.status_code == 200
        # A new name whose slug collides with an existing slug gets a suffix.
        BlogCategory.objects.create(name="Zoning rules", slug="zoning")
        clash = studio_client.post(f"{POSTS}categories/", {"name": "Zoning"}, format="json")
        assert clash.status_code == 201
        assert clash.json()["slug"].startswith("zoning-")
        author = Author.objects.create(name="Maya Ellison", role="Architect")
        found = studio_client.post(f"{POSTS}authors/", {"name": "maya ellison"}, format="json")
        assert found.json()["id"] == author.pk

    def test_detail_get_returns_the_editor_payload(self, studio_client):
        post = create_post(studio_client, title="Readable")
        response = studio_client.get(f"{POSTS}{post['id']}/")
        assert response.status_code == 200
        assert response.json()["title"] == "Readable"


class TestSlugs:
    def test_a_colliding_slug_is_refused_and_a_blank_one_is_regenerated(self, studio_client):
        first = create_post(studio_client, title="Same title")
        second = create_post(studio_client, title="Same title")
        assert second["slug"].startswith("same-title-")  # unique_slug walked to a suffix
        clash = studio_client.patch(
            f"{POSTS}{second['id']}/", {"slug": first["slug"]}, format="json"
        )
        assert clash.status_code == 400
        assert "already uses" in str(clash.json())
        blank = studio_client.patch(f"{POSTS}{second['id']}/", {"slug": ""}, format="json")
        assert blank.status_code == 200
        assert blank.json()["slug"].startswith("same-title")
        renamed = studio_client.patch(
            f"{POSTS}{second['id']}/", {"slug": "a-fresh-address"}, format="json"
        )
        assert renamed.status_code == 200
        assert renamed.json()["slug"] == "a-fresh-address"
