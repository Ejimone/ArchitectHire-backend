from rest_framework import serializers

from apps.catalog.models import Addon
from apps.jurisdictions.models import State

from .models import COMMERCIAL_SCOPES, RESIDENTIAL_SCOPES, TIMELINES, Estimate
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
