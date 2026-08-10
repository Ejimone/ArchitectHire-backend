from rest_framework import serializers

from .models import (
    Addon,
    DraftingConfig,
    Plan,
    ProjectType,
    RenderDeliverable,
    Service,
    ServiceCategory,
)


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "name",
            "slug",
            "description",
            "price_display",
            "price_unit",
            "detail_href",
            "tier",
            "requires_stamp",
            "is_popular",
        ]


class ServiceCategorySerializer(serializers.ModelSerializer):
    services = ServiceSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceCategory
        fields = [
            "name",
            "slug",
            "icon",
            "tagline",
            "has_detail",
            "detail_href",
            "from_price",
            "services",
        ]


class AddonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Addon
        fields = ["key", "label", "sub", "price"]


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["key", "tag", "title", "blurb", "points", "cta_label", "is_recommended"]


class ProjectTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectType
        fields = ["group", "name", "slug", "sub", "price_display", "slot_id", "image_hint"]


class ProjectTypeDetailSerializer(ProjectTypeSerializer):
    class Meta(ProjectTypeSerializer.Meta):
        fields = ProjectTypeSerializer.Meta.fields + [
            "short_name",
            "kicker",
            "h1",
            "intro",
            "body",
            "price_range",
            "bar_pct",
            "stats",
            "includes",
            "price_notes",
            "steps",
            "related",
        ]


class RenderDeliverableSerializer(serializers.ModelSerializer):
    class Meta:
        model = RenderDeliverable
        fields = ["name", "unit", "conceptual", "professional", "photoreal"]


class DraftingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = DraftingConfig
        fields = [
            "hourly_rate",
            "asbuilt_per_sf",
            "asbuilt_minimum",
            "per_sheet",
            "stamp_fee",
            "rush_pct",
        ]
