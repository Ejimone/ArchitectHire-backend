"""String representations, derived properties and admin display helpers.

These are what the owner actually sees in Django admin (change lists, previews,
bulk actions), so they are covered the same way any other surface is.
"""

import pytest
from django.contrib.admin.sites import site

from apps.cms import models as cms
from apps.cms import models_editorial as editorial
from apps.cms.admin import (
    CopyBlockAdmin,
    FAQAdmin,
    HeroCarouselSlideAdmin,
    MediaAssetAdmin,
)
from apps.cms.admin_editorial import (
    BlogPostAdmin,
    CaseStudyAdmin,
    ContactSubmissionAdmin,
    NewsletterSubscriberAdmin,
)


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (cms.SiteSettings(), "Site settings"),
        (cms.SocialLink(platform="LinkedIn"), "LinkedIn"),
        (cms.MediaAsset(slot_key="landing-hero"), "landing-hero"),
        (cms.NavGroup(menu="services", heading="Design"), "services · Design"),
        (cms.NavGroup(menu="projects", heading=""), "projects · group"),
        (cms.NavItem(label="Backyard ADU"), "Backyard ADU"),
        (cms.FooterColumn(heading="Company"), "Company"),
        (cms.FooterLink(label="About"), "About"),
        (cms.FAQ(question="How much does it cost?"), "How much does it cost?"),
        (cms.Stat(value="3,200+", label="projects"), "3,200+ projects"),
        (cms.Step(title="Tell us about the project"), "Tell us about the project"),
        (
            cms.Testimonial(name="Dana", quote="Permit set in six weeks"),
            "Dana: Permit set in six weeks",
        ),
        (cms.ValueProp(title="Licensed & verified"), "Licensed & verified"),
        (cms.TrustLogo(name="AIA"), "AIA"),
        (cms.CredentialBadge(label="NCARB"), "NCARB"),
        (cms.UseCase(title="Backyard ADU"), "Backyard ADU"),
        (cms.Persona(title="THE CLIENT"), "THE CLIENT"),
        (cms.Principle(title="Transparent pricing"), "Transparent pricing"),
        (cms.HeroCarouselSlide(caption="Oakland ADU"), "Oakland ADU"),
        (cms.HeroCarouselSlide(id=7, caption=""), "Slide 7"),
        (cms.CaseCard(title="Backyard ADU, Oakland"), "Backyard ADU, Oakland"),
        (
            cms.EstimateTeaserOption(label="Backyard ADU", price_range="$2,400 – $6,500"),
            "Backyard ADU ($2,400 – $6,500)",
        ),
        (cms.FeatureMatrixRow(label="Jurisdiction lookup"), "Jurisdiction lookup"),
        (cms.CopyBlock(scope="landing", key="hero-cta"), "landing:hero-cta"),
        (cms.PageSEO(page_key="landing"), "landing"),
        (editorial.Author(name="Maya Ellison, AIA"), "Maya Ellison, AIA"),
        (editorial.BlogCategory(name="Permits"), "Permits"),
        (editorial.BlogPost(title="ADU permits, explained"), "ADU permits, explained"),
        (
            editorial.BlogContentBlock(kind="paragraph", text="Setbacks matter."),
            "paragraph: Setbacks matter.",
        ),
        (editorial.CaseStudyCategory(name="ADU"), "ADU"),
        (editorial.CaseStudy(title="Backyard ADU"), "Backyard ADU"),
        (editorial.Department(name="Engineering"), "Engineering"),
        (editorial.JobPosting(title="Backend engineer"), "Backend engineer"),
        (editorial.Perk(title="Remote-first"), "Remote-first"),
        (editorial.ContactMethod(kind="CLIENTS", title="Talk to us"), "CLIENTS: Talk to us"),
        (editorial.ContactTopic(label="Billing"), "Billing"),
        (editorial.ContactSubmission(name="Dana", topic="Billing"), "Dana · Billing"),
        (editorial.PolicyPage(title="Privacy Policy"), "Privacy Policy"),
        (editorial.PolicySection(heading="What we collect"), "What we collect"),
        (editorial.InspirationItem(title="Warm minimal kitchen"), "Warm minimal kitchen"),
        (editorial.NewsletterSubscriber(email="sub@example.com"), "sub@example.com"),
    ],
)
def test_str(obj, expected):
    assert str(obj) == expected


def test_testimonial_str_truncates_long_quotes():
    quote = "A" * 100
    assert str(cms.Testimonial(name="Dana", quote=quote)) == f"Dana: {'A' * 40}"


def test_persona_points_list_drops_blank_lines():
    persona = cms.Persona(points="Fixed quote\n\n  Licensed architect  \n")
    assert persona.points_list == ["Fixed quote", "Licensed architect"]


def test_estimate_teaser_includes_list_drops_blank_lines():
    option = cms.EstimateTeaserOption(includes="Permit set\n\n  Structural  \n")
    assert option.includes_list == ["Permit set", "Structural"]


def test_feature_matrix_marks_are_left_to_right():
    """One cell per plan column, in the order the pricing table renders them."""
    row = cms.FeatureMatrixRow(
        label="Jurisdiction lookup",
        tier1=cms.FeatureMatrixRow.Mark.LIMITED,
        tier2=cms.FeatureMatrixRow.Mark.YES,
        tier3=cms.FeatureMatrixRow.Mark.YES,
    )
    assert row.marks == ["limited", "yes", "yes"]
    assert cms.FeatureMatrixRow(label="Client updates").marks == ["no", "no", "no"]


@pytest.mark.django_db
class TestScopedBlockAdminActions:
    def test_publish_and_unpublish_selected(self):
        faq = cms.FAQ.objects.create(
            scope="landing", question="QA-Action?", answer="A", status="draft"
        )
        model_admin = FAQAdmin(cms.FAQ, site)
        queryset = cms.FAQ.objects.filter(pk=faq.pk)

        model_admin.publish_selected(None, queryset)
        faq.refresh_from_db()
        assert faq.status == "published"
        assert faq.published_at is not None

        model_admin.unpublish_selected(None, queryset)
        faq.refresh_from_db()
        assert faq.status == "draft"


class TestAdminDisplayHelpers:
    def test_carousel_thumbnail_with_and_without_image(self):
        model_admin = HeroCarouselSlideAdmin(cms.HeroCarouselSlide, site)
        with_image = cms.HeroCarouselSlide(scope="landing", image="cms/carousel/slide.jpg")
        assert "<img" in model_admin.thumbnail(with_image)
        assert "cms/carousel/slide.jpg" in model_admin.thumbnail(with_image)
        assert model_admin.thumbnail(cms.HeroCarouselSlide(scope="landing")) == "—"

    def test_media_asset_thumbnail_with_and_without_image(self):
        model_admin = MediaAssetAdmin(cms.MediaAsset, site)
        with_image = cms.MediaAsset(slot_key="landing-hero", image="cms/slots/hero.jpg")
        assert "<img" in model_admin.thumbnail(with_image)
        assert model_admin.thumbnail(cms.MediaAsset(slot_key="landing-hero")) == "—"

    def test_copy_block_short_text(self):
        model_admin = CopyBlockAdmin(cms.CopyBlock, site)
        assert model_admin.short_text(cms.CopyBlock(text="Short copy")) == "Short copy"
        long_text = "x" * 200
        assert model_admin.short_text(cms.CopyBlock(text=long_text)) == "x" * 80 + "…"


@pytest.mark.django_db
class TestEditorialAdmin:
    def test_blog_post_publish_action(self):
        post = editorial.BlogPost.objects.create(
            slug="qa-admin-post", title="QA admin post", status="draft"
        )
        BlogPostAdmin(editorial.BlogPost, site).publish_selected(
            None, editorial.BlogPost.objects.filter(pk=post.pk)
        )
        post.refresh_from_db()
        assert post.status == "published"

    def test_case_study_publish_action(self):
        case = editorial.CaseStudy.objects.create(
            slug="qa-admin-case", title="QA admin case", status="draft"
        )
        CaseStudyAdmin(editorial.CaseStudy, site).publish_selected(
            None, editorial.CaseStudy.objects.filter(pk=case.pk)
        )
        case.refresh_from_db()
        assert case.status == "published"

    def test_inbound_records_cannot_be_added_by_hand(self):
        assert (
            ContactSubmissionAdmin(editorial.ContactSubmission, site).has_add_permission(None)
            is False
        )
        assert (
            NewsletterSubscriberAdmin(editorial.NewsletterSubscriber, site).has_add_permission(None)
            is False
        )
