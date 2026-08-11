from rest_framework import serializers

from apps.jurisdictions.models import State

from .models import (
    ArchitectProfile,
    Credential,
    Discipline,
    ExpertProfile,
    PortfolioItem,
    Review,
)


class DisciplineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discipline
        fields = [
            "key",
            "name",
            "description",
            "typical_rate",
            "licensure_tag",
            "requires_license",
            "requires_onsite",
            "icon",
        ]


class StateCodesField(serializers.SlugRelatedField):
    def __init__(self, **kwargs):
        super().__init__(
            slug_field="code", queryset=State.objects.all(), many=True, required=False, **kwargs
        )


class ArchitectProfileSerializer(serializers.ModelSerializer):
    licensed_states = serializers.SlugRelatedField(
        slug_field="code", queryset=State.objects.all(), many=True, required=False
    )
    project_types = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=ArchitectProfile.project_types.field.related_model.objects.all(),
        many=True,
        required=False,
    )
    headshot = serializers.ImageField(required=False, use_url=True)

    class Meta:
        model = ArchitectProfile
        fields = [
            "firm_name",
            "title",
            "years_licensed",
            "website",
            "bio",
            "headshot",
            "role_label",
            "engagement_mode",
            "hourly_rate",
            "typical_turnaround",
            "capacity",
            "accepting_work",
            "based_in",
            "travel_radius_mi",
            "remote_ok",
            "stamp_jurisdictions",
            "specialties",
            "business_entity",
            "w9_on_file",
            "licensed_states",
            "project_types",
            "onboarding_step",
            "onboarding_status",
            "rating",
            "review_count",
            "projects_delivered",
            "on_time_rate",
            "avg_response",
        ]
        read_only_fields = [
            "onboarding_status",
            "rating",
            "review_count",
            "projects_delivered",
            "on_time_rate",
            "avg_response",
        ]


class ExpertProfileSerializer(serializers.ModelSerializer):
    licensed_states = serializers.SlugRelatedField(
        slug_field="code", queryset=State.objects.all(), many=True, required=False
    )
    disciplines = serializers.SlugRelatedField(
        slug_field="key", queryset=Discipline.objects.all(), many=True, required=False
    )
    headshot = serializers.ImageField(required=False, use_url=True)
    requires_license = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExpertProfile
        fields = [
            "studio_name",
            "years_experience",
            "bio",
            "headshot",
            "disciplines",
            "software",
            "deliverables",
            "pricing_mode",
            "hourly_rate",
            "typical_turnaround",
            "capacity",
            "accepting_work",
            "based_in",
            "onsite_radius_mi",
            "remote_ok",
            "business_entity",
            "w9_on_file",
            "licensed_states",
            "requires_license",
            "onboarding_step",
            "onboarding_status",
            "rating",
            "review_count",
        ]
        read_only_fields = ["onboarding_status", "rating", "review_count"]


class CredentialSerializer(serializers.ModelSerializer):
    issuing_state = serializers.SlugRelatedField(
        slug_field="code", queryset=State.objects.all(), required=False, allow_null=True
    )
    document = serializers.FileField(required=False, use_url=True)

    class Meta:
        model = Credential
        fields = [
            "id",
            "kind",
            "issuing_state",
            "number",
            "label",
            "expiration_date",
            "coverage_amount",
            "document",
            "status",
            "verified_at",
            "review_notes",
        ]
        read_only_fields = ["status", "verified_at", "review_notes"]


class PortfolioItemSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(required=False, use_url=True)

    class Meta:
        model = PortfolioItem
        fields = ["id", "image", "title", "meta", "sort_order"]


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["reviewer_name", "reviewer_role", "rating", "text", "created_at"]


class PublicArchitectSerializer(serializers.ModelSerializer):
    """Public profile card/detail (design: Matches profile page)."""

    name = serializers.SerializerMethodField()
    avatar_url = serializers.CharField(source="user.avatar_url", read_only=True)
    licensed_states = serializers.SlugRelatedField(slug_field="code", many=True, read_only=True)
    portfolio = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    verified_credentials = serializers.SerializerMethodField()
    headshot = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = ArchitectProfile
        fields = [
            "name",
            "avatar_url",
            "headshot",
            "firm_name",
            "role_label",
            "bio",
            "based_in",
            "years_licensed",
            "engagement_mode",
            "hourly_rate",
            "rating",
            "review_count",
            "projects_delivered",
            "on_time_rate",
            "avg_response",
            "specialties",
            "licensed_states",
            "portfolio",
            "reviews",
            "verified_credentials",
        ]

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.email

    def get_portfolio(self, obj):
        items = obj.user.portfolio_items.all()[:8]
        return PortfolioItemSerializer(items, many=True, context=self.context).data

    def get_reviews(self, obj):
        reviews = obj.user.reviews_received.filter(is_published=True)[:6]
        return ReviewSerializer(reviews, many=True).data

    def get_verified_credentials(self, obj):
        results = []
        for c in obj.user.credentials.filter(status=Credential.Status.VERIFIED):
            state_name = c.issuing_state.name if c.issuing_state else ""
            label = c.label or f"{state_name} {c.get_kind_display()}".strip()
            results.append({"kind": c.get_kind_display(), "label": label, "number": c.number})
        return results
