from rest_framework import serializers

from .models import (
    FAQ,
    CaseCard,
    CredentialBadge,
    EstimateTeaserOption,
    FeatureMatrixRow,
    FooterColumn,
    HeroCarouselSlide,
    MediaAsset,
    NavGroup,
    NavItem,
    PageSEO,
    Persona,
    Principle,
    SiteSettings,
    SocialLink,
    Stat,
    Step,
    Testimonial,
    TrustLogo,
    UseCase,
    ValueProp,
)


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["id", "group", "question", "answer"]


class StatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stat
        fields = ["id", "group", "value", "label"]


class StepSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = Step
        fields = ["id", "group", "title", "description", "image"]


class TestimonialSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = Testimonial
        fields = ["id", "group", "quote", "name", "role", "audience", "photo"]


class ValuePropSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValueProp
        fields = ["id", "group", "icon", "title", "description"]


class TrustLogoSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = TrustLogo
        fields = ["id", "group", "name", "image"]


class CredentialBadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CredentialBadge
        fields = ["id", "group", "label"]


class UseCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = UseCase
        fields = ["id", "group", "icon", "title", "description", "cta_label", "href"]


class PersonaSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)
    points = serializers.ListField(
        source="points_list", child=serializers.CharField(), read_only=True
    )

    class Meta:
        model = Persona
        fields = [
            "id",
            "group",
            "kicker",
            "title",
            "body",
            "points",
            "image",
            "cta_label",
            "cta_href",
        ]


class CaseCardSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = CaseCard
        fields = [
            "id",
            "group",
            "category_tag",
            "location",
            "title",
            "excerpt",
            "image",
            "href",
            "stat1_value",
            "stat1_label",
            "stat2_value",
            "stat2_label",
        ]


class EstimateTeaserOptionSerializer(serializers.ModelSerializer):
    includes = serializers.ListField(
        source="includes_list", child=serializers.CharField(), read_only=True
    )

    class Meta:
        model = EstimateTeaserOption
        fields = ["id", "group", "label", "price_range", "bar_pct", "includes"]


class FeatureMatrixRowSerializer(serializers.ModelSerializer):
    marks = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = FeatureMatrixRow
        fields = ["id", "group", "label", "is_flagship", "marks"]


class PrincipleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Principle
        fields = ["id", "group", "title", "body"]


class HeroCarouselSlideSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = HeroCarouselSlide
        fields = ["id", "group", "image", "caption", "name"]


class PageSEOSerializer(serializers.ModelSerializer):
    og_image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = PageSEO
        fields = ["title", "description", "og_image", "canonical"]


class SiteSettingsSerializer(serializers.ModelSerializer):
    hero_image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = SiteSettings
        fields = [
            "promo_banner_enabled",
            "promo_banner_text",
            "promo_banner_cta_label",
            "promo_banner_cta_href",
            "trust_bar_enabled",
            "hero_media_mode",
            "hero_image",
            "hero_video_url",
            "contact_email_clients",
            "contact_email_support",
            "contact_email_privacy",
        ]


class SocialLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLink
        fields = ["platform", "url"]


class NavItemSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = NavItem
        fields = ["label", "sublabel", "href", "price_hint", "is_featured", "image"]


class NavGroupSerializer(serializers.ModelSerializer):
    items = NavItemSerializer(many=True, read_only=True)

    class Meta:
        model = NavGroup
        fields = ["menu", "heading", "items"]


class FooterColumnSerializer(serializers.ModelSerializer):
    links = serializers.SerializerMethodField()

    class Meta:
        model = FooterColumn
        fields = ["heading", "links"]

    def get_links(self, obj):
        return [{"label": link.label, "href": link.href} for link in obj.links.all()]


class MediaAssetSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = MediaAsset
        fields = ["slot_key", "image", "alt_text"]
