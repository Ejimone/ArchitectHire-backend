from rest_framework import serializers

from apps.catalog.models import Addon, ProjectType
from apps.jurisdictions.models import State
from apps.providers.models import ArchitectProfile

from .matching import find_matches
from .models import COMMERCIAL_SCOPES, RESIDENTIAL_SCOPES, TIMELINES, Estimate, Match, Project
from .pricing import (
    BATHS_OPTIONS,
    BEDS_OPTIONS,
    BUDGET_OPTIONS,
    CONSULT_TYPES,
    DRAFTING_HAVE_OPTIONS,
    DRAFTING_SERVICES,
    ENGINEERING_TYPES,
    GOALS,
    ROOM_KEYS,
    SCAN_TYPES,
    SITE_OPTIONS,
    STORIES_OPTIONS,
    STYLE_OPTIONS,
    VIZ_HAVE_OPTIONS,
    VIZ_TYPES,
    compute_quote,
)

PROJECT_KINDS = ["Residential", "Commercial"]


class DesignAnswersSerializer(serializers.Serializer):
    """Design-branch answers that shape the brief but never the price."""

    beds = serializers.ChoiceField(choices=BEDS_OPTIONS, default="3")
    baths = serializers.ChoiceField(choices=BATHS_OPTIONS, default="2")
    stories = serializers.ChoiceField(choices=STORIES_OPTIONS, default="2 stories")
    style = serializers.ChoiceField(choices=STYLE_OPTIONS, default="Modern")
    rooms = serializers.DictField(child=serializers.BooleanField(), required=False)
    budget = serializers.ChoiceField(choices=BUDGET_OPTIONS, default="$500k – $1M")
    site = serializers.ChoiceField(choices=SITE_OPTIONS, default="Yes, I own it")

    def validate_rooms(self, value):
        unknown = set(value) - set(ROOM_KEYS)
        if unknown:
            raise serializers.ValidationError(f"Unknown areas: {', '.join(sorted(unknown))}")
        return value


class DraftingAnswersSerializer(serializers.Serializer):
    ptype = serializers.ChoiceField(choices=PROJECT_KINDS, default="Residential")
    service = serializers.ChoiceField(choices=DRAFTING_SERVICES, default="CAD drafting")
    hours = serializers.IntegerField(min_value=2, max_value=40, default=8)
    dsqft = serializers.IntegerField(min_value=400, max_value=6000, default=1500)
    sheets = serializers.IntegerField(min_value=1, max_value=40, default=6)
    stamp = serializers.BooleanField(default=False)
    have = serializers.ChoiceField(choices=DRAFTING_HAVE_OPTIONS, default="Sketch or dims")
    rush = serializers.BooleanField(default=False)


class ConsultAnswersSerializer(serializers.Serializer):
    ptype = serializers.ChoiceField(choices=PROJECT_KINDS, default="Residential")
    consultType = serializers.ChoiceField(choices=CONSULT_TYPES, default="Video consult")


class VizAnswersSerializer(serializers.Serializer):
    ptype = serializers.ChoiceField(choices=PROJECT_KINDS, default="Residential")
    vizType = serializers.ChoiceField(choices=VIZ_TYPES, default="Single render")
    vizQty = serializers.IntegerField(min_value=1, max_value=10, default=1)
    vizSecs = serializers.IntegerField(min_value=10, max_value=120, default=30)
    vizHave = serializers.ChoiceField(choices=VIZ_HAVE_OPTIONS, default="CAD / model")


class ScanAnswersSerializer(serializers.Serializer):
    ptype = serializers.ChoiceField(choices=PROJECT_KINDS, default="Residential")
    scanType = serializers.ChoiceField(choices=SCAN_TYPES, default="3D laser scanning")
    scanArea = serializers.IntegerField(min_value=500, max_value=50000, default=2500)


class EngineeringAnswersSerializer(serializers.Serializer):
    ptype = serializers.ChoiceField(choices=PROJECT_KINDS, default="Residential")
    engType = serializers.ChoiceField(choices=ENGINEERING_TYPES, default="Structural stamp")
    engHours = serializers.IntegerField(min_value=1, max_value=20, default=4)


ANSWER_SERIALIZERS = {
    "design": DesignAnswersSerializer,
    "drafting": DraftingAnswersSerializer,
    "consult": ConsultAnswersSerializer,
    "viz": VizAnswersSerializer,
    "scan": ScanAnswersSerializer,
    "engineering": EngineeringAnswersSerializer,
}


class EstimateCreateSerializer(serializers.Serializer):
    """One endpoint, six branches (design/app/Get Started.dc.html).

    ``goal`` selects the pricing branch and therefore which ``answers`` schema
    applies. The design branch keeps the original flat contract (project_type,
    scope, sqft, timeline, addons) because those five answers *are* its price
    inputs; every branch's remaining answers travel in ``answers``.
    """

    goal = serializers.ChoiceField(choices=GOALS, default="design")
    state = serializers.CharField(max_length=2)
    answers = serializers.DictField(required=False, default=dict)

    project_type = serializers.ChoiceField(choices=PROJECT_KINDS, required=False)
    scope = serializers.CharField(max_length=40, required=False)
    sqft = serializers.IntegerField(min_value=200, max_value=8000, required=False)
    timeline = serializers.ChoiceField(choices=TIMELINES, required=False)
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
        goal = attrs["goal"]
        branch = ANSWER_SERIALIZERS[goal](data=attrs.get("answers") or {})
        if not branch.is_valid():
            raise serializers.ValidationError({"answers": branch.errors})
        answers = dict(branch.validated_data)

        if goal == "design":
            missing = {
                name: "This field is required."
                for name in ("project_type", "scope", "sqft", "timeline")
                if attrs.get(name) is None
            }
            if missing:
                raise serializers.ValidationError(missing)
            valid_scopes = (
                COMMERCIAL_SCOPES if attrs["project_type"] == "Commercial" else RESIDENTIAL_SCOPES
            )
            if attrs["scope"] not in valid_scopes:
                raise serializers.ValidationError(
                    {"scope": f"Must be one of: {', '.join(valid_scopes)}"}
                )
            answers.update(
                ptype=attrs["project_type"],
                scope=attrs["scope"],
                sqft=attrs["sqft"],
                timeline=attrs["timeline"],
                addons=attrs["addons"],
            )
        attrs["answers"] = answers
        return attrs

    def create(self, validated_data):
        state = validated_data["state"]
        goal = validated_data["goal"]
        answers = validated_data["answers"]
        quote = compute_quote(goal=goal, answers=answers, state=state)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return Estimate.objects.create(
            user=user if (user and user.is_authenticated) else None,
            goal=goal,
            answers=answers,
            quote=quote.view,
            project_type=quote.project_type,
            scope=quote.scope,
            sqft=quote.sqft,
            state=state,
            timeline=quote.timeline,
            addons=quote.addons,
            rate=round(quote.rate, 2),
            base=round(quote.base, 2),
            addon_total=round(quote.addon_total, 2),
            multiplier=round(quote.multiplier, 3),
            total=round(quote.total, 2),
            low=round(quote.low, 2),
            high=round(quote.high, 2),
        )


class EstimateSerializer(serializers.ModelSerializer):
    state = serializers.CharField(source="state.code", read_only=True)
    jurisdiction = serializers.SerializerMethodField()

    class Meta:
        model = Estimate
        fields = [
            "id",
            "goal",
            "project_type",
            "scope",
            "sqft",
            "state",
            "timeline",
            "addons",
            "answers",
            "quote",
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
