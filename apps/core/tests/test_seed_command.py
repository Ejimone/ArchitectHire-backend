"""Seed loader guard rails: bad arguments, missing seed files and patch errors."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands import seed as seed_module
from apps.core.management.commands.seed import Command, load, load_optional


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,catalog")


def command():
    return Command()


class TestSeedFileLoading:
    def test_required_seed_file_must_exist(self):
        with pytest.raises(CommandError, match="Missing seed file"):
            load("not-a-real-seed-file")

    def test_optional_seed_file_may_be_absent(self):
        assert load_optional("not-a-real-seed-file") is None


class TestArguments:
    def test_no_domain_is_an_error(self):
        with pytest.raises(CommandError, match="Pass --all or --domain"):
            call_command("seed")

    def test_unknown_domain_is_an_error(self):
        with pytest.raises(CommandError, match="Unknown domain 'atlantis'"):
            call_command("seed", "--domain", "atlantis")


@pytest.mark.django_db
class TestUnmatchedSeedRows:
    def test_city_in_an_unknown_state_is_skipped(self, monkeypatch):
        from apps.jurisdictions.models import City

        real_load = seed_module.load

        def fake_load(name):
            if name == "cities":
                return [
                    {
                        "slug": "qa-atlantis-city",
                        "name": "Atlantis",
                        "state": "Not A Real State",
                        "architect_count": "1",
                    }
                ]
            return real_load(name)

        monkeypatch.setattr(seed_module, "load", fake_load)
        command().seed_jurisdictions()
        assert not City.objects.filter(slug="qa-atlantis-city").exists()

    def test_landing_content_for_an_unknown_project_type_is_skipped(self, monkeypatch, seeded):
        real_load_optional = seed_module.load_optional

        def fake_load_optional(name):
            if name == "project_landing":
                return {"Not A Real Project Type": {"short": "nope"}}
            return real_load_optional(name)

        monkeypatch.setattr(seed_module, "load_optional", fake_load_optional)
        command().seed_catalog()  # must not raise


@pytest.mark.django_db
class TestPatchFiles:
    def _patches(self, monkeypatch, tmp_path, payload):
        directory = tmp_path / "patches"
        directory.mkdir()
        (directory / "qa-patch.json").write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(seed_module, "SEEDS", tmp_path)

    def test_missing_patches_directory_is_a_no_op(self, monkeypatch, tmp_path):
        monkeypatch.setattr(seed_module, "SEEDS", tmp_path)
        command()._seed_patches()  # no seeds/patches/ — returns quietly

    @pytest.mark.parametrize("section", ["blocks", "delete"])
    def test_unknown_block_type_is_an_error(self, monkeypatch, tmp_path, section):
        self._patches(monkeypatch, tmp_path, {section: {"not-a-block-type": []}})
        with pytest.raises(CommandError, match="unknown block type 'not-a-block-type'"):
            command()._seed_patches()

    def test_state_rows_patch_existing_states(self, monkeypatch, tmp_path, seeded):
        from apps.jurisdictions.models import State

        self._patches(
            monkeypatch,
            tmp_path,
            {"states": [{"code": "CA", "intro": "QA patched intro"}]},
        )
        command()._seed_patches()
        assert State.objects.get(code="CA").intro == "QA patched intro"

    def test_project_type_and_city_rows_patch_existing_records(
        self, monkeypatch, tmp_path, seeded
    ):
        from apps.catalog.models import ProjectType
        from apps.jurisdictions.models import City

        self._patches(
            monkeypatch,
            tmp_path,
            {
                "project_types": [{"slug": "backyard-adu", "intro": "QA patched project intro"}],
                "cities": [{"slug": "oakland", "intro": "QA patched city intro"}],
            },
        )
        command()._seed_patches()
        assert ProjectType.objects.get(slug="backyard-adu").intro == "QA patched project intro"
        assert City.objects.get(slug="oakland").intro == "QA patched city intro"


@pytest.mark.django_db
class TestEditorialPatches:
    """`editorial` patches author whole child rows, so re-running must be idempotent."""

    @pytest.fixture
    def editorial(self):
        from apps.cms.models import (
            BlogContentBlock,
            BlogPost,
            CaseStudy,
            CaseStudyCategory,
            CaseStudyImage,
            PolicyPage,
            PolicySection,
        )

        CaseStudyCategory.objects.create(name="QA Patch Category", slug="qa-patch-category")
        post = BlogPost.objects.create(slug="qa-patch-post", title="QA patch post")
        BlogContentBlock.objects.create(post=post, kind="paragraph", text="Old", sort_order=0)
        body_post = BlogPost.objects.create(slug="qa-patch-body", title="QA patch body")
        BlogContentBlock.objects.create(post=body_post, kind="paragraph", text="Stale")
        case = CaseStudy.objects.create(slug="qa-patch-case", title="QA patch case")
        CaseStudyImage.objects.create(case_study=case, caption="Stale")
        page = PolicyPage.objects.create(slug="qa-patch-policy", title="QA patch policy")
        PolicySection.objects.create(page=page, anchor="collect", heading="Old", body="Old")
        return post, body_post, case, page

    def test_every_editorial_patch_shape(self, editorial):
        from apps.cms.models import Author, BlogPost, CaseStudy, PolicySection

        post, body_post, case, page = editorial

        updated = command()._patch_editorial(
            {
                "authors": [{"name": "QA Patch Author", "role": "Architect"}],
                "blog_posts": [{"slug": "qa-patch-post", "dek": "QA dek"}],
                "blog_blocks": [{"post": "qa-patch-post", "sort_order": 0, "text": "QA replaced"}],
                "blog_bodies": [
                    {
                        "post": "qa-patch-body",
                        "author": "QA Patch Author",
                        "blocks": [
                            {"kind": "h2", "text": "QA heading"},
                            {"kind": "paragraph", "text": "QA paragraph"},
                        ],
                    },
                    {"post": "qa-no-such-post", "blocks": []},  # skipped
                ],
                "case_studies": [
                    {
                        "slug": "qa-patch-case",
                        "dek": "QA case dek",
                        "category": "QA Patch Category",
                    }
                ],
                "case_study_galleries": [
                    {
                        "case_study": "qa-patch-case",
                        "images": [{"caption": "QA image one"}, {"caption": "QA image two"}],
                    },
                    {"case_study": "qa-no-such-case", "images": []},  # skipped
                ],
                "policy_sections": [
                    {"page": "qa-patch-policy", "anchor": "collect", "heading": "QA heading"}
                ],
            }
        )

        assert updated > 0
        assert Author.objects.filter(name="QA Patch Author").exists()
        assert BlogPost.objects.get(slug="qa-patch-post").dek == "QA dek"
        assert post.content_blocks.get(sort_order=0).text == "QA replaced"

        body_post.refresh_from_db()
        assert body_post.author.name == "QA Patch Author"
        assert [b.text for b in body_post.content_blocks.all()] == ["QA heading", "QA paragraph"]

        patched_case = CaseStudy.objects.get(slug="qa-patch-case")
        assert patched_case.dek == "QA case dek"
        assert patched_case.category.name == "QA Patch Category"  # resolved by name, not pk
        assert [i.caption for i in case.gallery.all()] == ["QA image one", "QA image two"]
        assert PolicySection.objects.get(page=page, anchor="collect").heading == "QA heading"

    def test_empty_patch_touches_nothing(self, editorial):
        assert command()._patch_editorial({}) == 0


@pytest.mark.django_db
class TestPaymentsDomain:
    def test_a_zero_percent_fee_policy_is_created_when_none_is_active(self):
        from apps.payments.models import FeePolicy

        FeePolicy.objects.all().delete()
        command().seed_payments()
        policy = FeePolicy.objects.get(is_active=True)
        assert policy.percent == 0
        assert policy.note == "Platform takes 0% of a project"

    def test_an_existing_active_policy_is_left_alone(self):
        from apps.payments.models import FeePolicy

        FeePolicy.objects.all().delete()
        existing = FeePolicy.objects.create(percent=5, is_active=True, note="QA policy")
        command().seed_payments()
        assert list(FeePolicy.objects.values_list("pk", flat=True)) == [existing.pk]


@pytest.mark.django_db
class TestMissingContentFiles:
    """Content seeds are optional — a fresh checkout without them still seeds."""

    @pytest.fixture(autouse=True)
    def no_content_files(self, monkeypatch):
        monkeypatch.setattr(seed_module, "load_optional", lambda name: None)

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("_seed_copy", "content_copy.json missing"),
            ("_seed_scoped_blocks", "content_blocks.json missing"),
            ("_seed_editorial", "content_editorial.json missing"),
            ("_seed_seo", "content_seo.json missing"),
        ],
    )
    def test_missing_file_warns_and_skips(self, method, expected, capsys):
        getattr(command(), method)()
        assert expected in capsys.readouterr().out


@pytest.mark.django_db
class TestPolicyPagePatches(TestPatchFiles):

    def test_policy_pages_are_created_whole(self, monkeypatch, tmp_path):
        from apps.cms.models import PolicyPage

        self._patches(
            monkeypatch,
            tmp_path,
            {
                "editorial": {
                    "policy_pages": [
                        {
                            "slug": "qa-terms",
                            "title": "Terms of Service",
                            "effective_date": "2026-08-11",
                            "sections": [
                                {"anchor": "scope", "heading": "1. Scope", "body": "QA body", "sort": 0},
                                {"anchor": "fees", "heading": "2. Fees", "body": "QA fees", "sort": 1},
                            ],
                        }
                    ]
                }
            },
        )
        command()._seed_patches()
        page = PolicyPage.objects.get(slug="qa-terms")
        assert page.title == "Terms of Service"
        assert list(page.sections.values_list("anchor", flat=True)) == ["scope", "fees"]

        # Re-running converges instead of duplicating sections.
        command()._seed_patches()
        assert PolicyPage.objects.get(slug="qa-terms").sections.count() == 2
