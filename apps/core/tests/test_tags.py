"""Which frontend cache tags each content model claims.

This vocabulary is a contract with the frontend's revalidate route: a tag the backend
emits and the frontend does not attach to any fetch purges nothing, and a page the
backend never names goes stale until an unrelated write happens to purge it. Both
halves are silent failures, so every model family is pinned here.
"""

import pytest
from django.apps import apps as global_apps

from apps.catalog import models as catalog
from apps.cms import models as cms
from apps.cms import models_editorial as editorial
from apps.cms.views import BLOCK_REGISTRY
from apps.core.tags import _TAGS_BY_MODEL, tags_for
from apps.jurisdictions import models as jurisdictions
from apps.payments import models as payments


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        # Site chrome.
        (cms.SiteSettings(), {"cms", "cms:settings"}),
        (cms.NavGroup(menu="services"), {"cms:nav"}),
        (cms.NavItem(label="Backyard ADU"), {"cms:nav"}),
        (cms.FooterColumn(heading="Company"), {"cms:footer"}),
        (cms.FooterLink(label="About"), {"cms:footer"}),
        (cms.SocialLink(platform="LinkedIn"), {"cms:footer"}),
        # Page-scoped content.
        (cms.CopyBlock(scope="landing", key="hero-cta"), {"cms:page:landing"}),
        (cms.PageSEO(page_key="about"), {"cms:page:about"}),
        (cms.MediaAsset(slot_key="landing:hero-arch"), {"cms:page:landing"}),
        # The scope in a slot key carries its own colon; splitting from the left would
        # purge a page called "city".
        (cms.MediaAsset(slot_key="city:oakland:work-1"), {"cms:page:city:oakland"}),
        # Editorial.
        (editorial.Author(name="Maya Ellison, AIA"), {"cms:blog"}),
        (editorial.BlogCategory(name="Permits"), {"cms:blog"}),
        (editorial.BlogPost(slug="adu-permits"), {"cms:blog", "cms:blog:adu-permits"}),
        (
            editorial.BlogContentBlock(post=editorial.BlogPost(slug="adu-permits")),
            {"cms:blog", "cms:blog:adu-permits"},
        ),
        (editorial.CaseStudyCategory(name="ADU"), {"cms:cases"}),
        (editorial.CaseStudy(slug="oakland-adu"), {"cms:cases", "cms:case:oakland-adu"}),
        (
            editorial.CaseStudyImage(case_study=editorial.CaseStudy(slug="oakland-adu")),
            {"cms:cases", "cms:case:oakland-adu"},
        ),
        (editorial.PolicyPage(slug="privacy"), {"cms:policies:privacy"}),
        (
            editorial.PolicySection(page=editorial.PolicyPage(slug="terms")),
            {"cms:policies:terms"},
        ),
        (editorial.Department(name="Engineering"), {"cms:careers"}),
        (editorial.JobPosting(title="Backend engineer"), {"cms:careers"}),
        (editorial.Perk(title="Remote-first"), {"cms:careers"}),
        (editorial.ContactMethod(title="Talk to us"), {"cms:contact"}),
        (editorial.ContactTopic(label="Billing"), {"cms:contact"}),
        (editorial.InspirationItem(title="Warm minimal kitchen"), {"cms:inspiration"}),
        # Inbound rows: narrow tags, because the public can create these at will.
        (editorial.ContactSubmission(name="Dana"), {"cms:contact"}),
        (editorial.NewsletterSubscriber(email="sub@example.com"), {"cms:contact"}),
        (editorial.InspirationLike(), {"cms:inspiration"}),
        # Catalog.
        (
            catalog.ProjectType(slug="adu"),
            {"cms:catalog", "cms:catalog:project-type:adu", "cms:page:project-type:adu"},
        ),
        (catalog.Plan(title="Starter"), {"cms:catalog", "cms:catalog:plans"}),
        (catalog.Service(slug="3d-visualization"), {"cms:catalog"}),
        (catalog.ServiceCategory(slug="rendering"), {"cms:catalog"}),
        (catalog.DraftingConfig(), {"cms:catalog"}),
        # Jurisdictions.
        (
            jurisdictions.State(code="CA"),
            {"cms:jurisdictions", "cms:jurisdictions:state:CA", "cms:page:state:CA"},
        ),
        (
            jurisdictions.City(slug="oakland"),
            {"cms:jurisdictions", "cms:jurisdictions:city:oakland", "cms:page:city:oakland"},
        ),
        # Payments: the plan table is content, the money movement around it is not.
        (payments.SubscriptionPlan(name="Practice"), {"cms:plans"}),
        (payments.EscrowTransaction(), {"cms"}),
    ],
)
def test_tags_for_a_written_row(instance, expected):
    assert tags_for(instance) == expected


def test_every_scoped_block_purges_exactly_its_own_page():
    """The 14 block types are interchangeable: each renders only where its scope says."""
    for _name, model, _serializer in BLOCK_REGISTRY:
        assert tags_for(model(scope="services")) == {"cms:page:services"}


def test_every_handler_names_a_model_that_exists():
    """A typo'd label is invisible otherwise — the row just gets the catch-all."""
    for label in _TAGS_BY_MODEL:
        assert global_apps.get_model(label) is not None


def test_no_cms_model_falls_through_to_the_catch_all():
    """Everything in cms is content, so a new model here needs its own tag rather
    than a purge of the entire site."""
    for model in global_apps.get_app_config("cms").get_models():
        assert model._meta.label_lower in _TAGS_BY_MODEL or issubclass(model, cms.ScopedBlock)
