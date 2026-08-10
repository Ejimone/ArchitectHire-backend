from rest_framework import serializers

from .models import (
    FAQ,
    CredentialBadge,
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
        fields = ["id", "question", "answer"]


class StatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stat
        fields = ["id", "value", "label"]


class StepSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = Step
        fields = ["id", "title", "description", "image"]


class TestimonialSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = Testimonial
        fields = ["id", "quote", "name", "role", "audience", "photo"]


class ValuePropSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValueProp
        fields = ["id", "icon", "title", "description"]


class TrustLogoSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = TrustLogo
        fields = ["id", "name", "image"]


class CredentialBadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CredentialBadge
        fields = ["id", "label"]


class UseCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = UseCase
        fields = ["id", "icon", "title", "description", "cta_label", "href"]


class PersonaSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)
    points = serializers.ListField(
        source="points_list", child=serializers.CharField(), read_only=True
    )

    class Meta:
        model = Persona
        fields = ["id", "kicker", "title", "body", "points", "image", "cta_label", "cta_href"]


class PrincipleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Principle
        fields = ["id", "title", "body"]


class HeroCarouselSlideSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = HeroCarouselSlide
        fields = ["id", "image", "caption", "name"]


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
