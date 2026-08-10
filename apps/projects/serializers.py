from rest_framework import serializers

from apps.catalog.models import Addon, ProjectType
from apps.jurisdictions.models import State
from apps.providers.models import ArchitectProfile

from .matching import find_matches
from .models import COMMERCIAL_SCOPES, RESIDENTIAL_SCOPES, TIMELINES, Estimate, Match, Project
from .pricing import compute_estimate


class EstimateCreateSerializer(serializers.Serializer):
    project_type = serializers.ChoiceField(choices=["Residential", "Commercial"])
    scope = serializers.CharField(max_length=40)
    sqft = serializers.IntegerField(min_value=200, max_value=8000)
    state = serializers.CharField(max_length=2)
    timeline = serializers.ChoiceField(choices=TIMELINES)
    addons = serializers.ListField(
        child=serializers.CharField(max_length=40), allow_empty=True, default=list
    )

    def validate_state(self, value):
        try:
            return State.objects.get(code=value.upper())
        except State.DoesNotExist:
            raise serializers.ValidationError("Unknown state code.") from None

    def validate_addons(self, value):
        known = set(Addon.objects.values_list("key", flat=True))
        unknown = set(value) - known
        if unknown:
            raise serializers.ValidationError(f"Unknown add-ons: {', '.join(sorted(unknown))}")
        return value

    def validate(self, attrs):
        valid_scopes = (
            COMMERCIAL_SCOPES if attrs["project_type"] == "Commercial" else RESIDENTIAL_SCOPES
        )
        if attrs["scope"] not in valid_scopes:
            raise serializers.ValidationError(
                {"scope": f"Must be one of: {', '.join(valid_scopes)}"}
            )
        return attrs

    def create(self, validated_data):
        state = validated_data["state"]
        result = compute_estimate(
            sqft=validated_data["sqft"],
            state=state,
            addon_keys=validated_data["addons"],
        )
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return Estimate.objects.create(
            user=user if (user and user.is_authenticated) else None,
            project_type=validated_data["project_type"],
            scope=validated_data["scope"],
            sqft=validated_data["sqft"],
            state=state,
            timeline=validated_data["timeline"],
            addons=result.addons,
            rate=round(result.rate, 2),
            base=round(result.base, 2),
            addon_total=round(result.addon_total, 2),
            multiplier=round(result.multiplier, 3),
            total=round(result.total, 2),
            low=round(result.low, 2),
            high=round(result.high, 2),
        )


class EstimateSerializer(serializers.ModelSerializer):
    state = serializers.CharField(source="state.code", read_only=True)
    jurisdiction = serializers.SerializerMethodField()

    class Meta:
        model = Estimate
        fields = [
            "id",
            "project_type",
            "scope",
            "sqft",
            "state",
            "timeline",
            "addons",
            "rate",
            "base",
            "addon_total",
            "multiplier",
            "total",
            "low",
            "high",
            "jurisdiction",
            "created_at",
        ]
        read_only_fields = fields

    def get_jurisdiction(self, obj):
        state = obj.state
        return {
            "code": state.code,
            "name": state.name,
            "score": state.complexity_score,
            "band": state.band_label,
            "multiplier": round(state.multiplier, 3),
            "factors": state.factors,
        }


class MatchSerializer(serializers.ModelSerializer):
    """Client-facing match card (design: Matches.dc.html)."""

    architect_name = serializers.SerializerMethodField()
    firm = serializers.SerializerMethodField()
    profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            "id",
            "architect_name",
            "firm",
            "profile_id",
            "score",
            "tag",
            "reasons",
            "rate_label",
            "rate_display",
            "status",
        ]

    def get_architect_name(self, obj):
        return obj.architect.get_full_name() or obj.architect.email

    def get_firm(self, obj):
        profile = ArchitectProfile.objects.filter(user=obj.architect).first()
        return profile.firm_name if profile else ""

    def get_profile_id(self, obj):
        profile = ArchitectProfile.objects.filter(user=obj.architect).first()
        return profile.pk if profile else None


class ProjectSerializer(serializers.ModelSerializer):
    state = serializers.CharField(source="state.code", read_only=True)
    matches = MatchSerializer(many=True, read_only=True)
    estimate = EstimateSerializer(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "title",
            "project_type",
            "scope",
            "sqft",
            "state",
            "timeline",
            "status",
            "progress_pct",
            "next_action",
            "architect",
            "estimate",
            "matches",
            "created_at",
        ]
        read_only_fields = fields


class ProjectCreateSerializer(serializers.Serializer):
    """Claim an estimate into a project and run matching."""

    estimate_id = serializers.UUIDField()

    def validate_estimate_id(self, value):
        try:
            estimate = Estimate.objects.select_related("state").get(pk=value)
        except Estimate.DoesNotExist:
            raise serializers.ValidationError("Unknown estimate.") from None
        if Project.objects.filter(estimate=estimate).exists():
            raise serializers.ValidationError("Estimate already claimed.")
        return estimate

    def create(self, validated_data):
        estimate = validated_data["estimate_id"]
        user = self.context["request"].user

        if estimate.user is None:
            estimate.user = user
            estimate.save(update_fields=["user"])

        project_type_ref = ProjectType.objects.filter(name__icontains=estimate.scope).first()
        project = Project.objects.create(
            owner=user,
            estimate=estimate,
            title=f"{estimate.scope} · {estimate.state.name}",
            project_type=estimate.project_type,
            project_type_ref=project_type_ref,
            scope=estimate.scope,
            sqft=estimate.sqft,
            state=estimate.state,
            timeline=estimate.timeline,
            progress_pct=12,
            next_action="Pick your architect",
        )

        for entry in find_matches(project):
            profile = entry["profile"]
            if profile.engagement_mode == "hourly" or entry["tag"] == "HOURLY OPTION":
                rate_label = "HOURLY RATE"
                rate_display = f"${profile.hourly_rate:.0f}/hr" if profile.hourly_rate else ""
            else:
                rate_label = "FIXED QUOTE"
                rate_display = f"${estimate.total:,.0f}"
            Match.objects.create(
                project=project,
                architect=profile.user,
                score=entry["score"],
                tag=entry["tag"],
                reasons=entry["reasons"],
                rate_label=rate_label,
                rate_display=rate_display,
            )
        return project


class LeadSerializer(serializers.ModelSerializer):
    """Architect-facing lead card (design: Architect Account dashboard)."""

    title = serializers.CharField(source="project.title", read_only=True)
    detail = serializers.SerializerMethodField()
    estimate_range = serializers.SerializerMethodField()
    engagement = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            "id",
            "title",
            "detail",
            "estimate_range",
            "engagement",
            "score",
            "status",
            "created_at",
        ]

    def get_detail(self, obj):
        project = obj.project
        return f"{project.sqft:,} sf · {project.scope} · within your license area"

    def get_estimate_range(self, obj):
        estimate = obj.project.estimate
        if estimate is None:
            return ""
        return f"${estimate.low:,.0f}–{estimate.high:,.0f}"

    def get_engagement(self, obj):
        return "Hourly · your rate" if obj.rate_label == "HOURLY RATE" else "Fixed quote"
