from rest_framework import serializers

from apps.projects.models import Project

from .models import (
    ChangeRequest,
    Deliverable,
    Engagement,
    Milestone,
    RequoteFlag,
    TimeEntry,
)


class MilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = [
            "id",
            "title",
            "description",
            "amount",
            "due_date",
            "status",
            "approved_at",
            "sort_order",
        ]
        read_only_fields = ["status", "approved_at"]


class ChangeRequestSerializer(serializers.ModelSerializer):
    markup = serializers.FileField(required=False, use_url=True)

    class Meta:
        model = ChangeRequest
        fields = ["id", "categories", "note", "markup", "created_at"]

    def validate_categories(self, value):
        unknown = set(value) - set(ChangeRequest.CATEGORY_CHOICES)
        if unknown:
            raise serializers.ValidationError(f"Unknown categories: {', '.join(sorted(unknown))}")
        return value


class RequoteFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequoteFlag
        fields = ["id", "old_total", "new_total", "reason", "status", "created_at", "resolved_at"]
        read_only_fields = ["old_total", "status", "resolved_at"]


class TimeEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeEntry
        fields = ["id", "date", "hours", "description", "created_at"]


class DeliverableSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=True)
    is_new = serializers.SerializerMethodField()

    class Meta:
        model = Deliverable
        fields = ["id", "file", "name", "size_bytes", "stamped", "is_new", "created_at"]
        read_only_fields = ["size_bytes"]

    def get_is_new(self, obj):
        from datetime import timedelta

        from django.utils import timezone

        return obj.created_at >= timezone.now() - timedelta(days=3)


class EngagementSerializer(serializers.ModelSerializer):
    project_title = serializers.CharField(source="project.title", read_only=True)
    milestones = MilestoneSerializer(many=True, read_only=True)
    deposit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    platform_fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Engagement
        fields = [
            "id",
            "project",
            "project_title",
            "client",
            "provider",
            "kind",
            "total",
            "hourly_rate",
            "fee_percent",
            "deposit_amount",
            "platform_fee",
            "status",
            "milestones",
            "created_at",
        ]
        read_only_fields = ["client", "provider", "fee_percent", "status"]


class EngagementCreateSerializer(serializers.Serializer):
    """Client creates the contract after hiring (design: contract → payment steps)."""

    project_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=[k for k, _ in Engagement.Kind.choices])

    def validate(self, attrs):
        request = self.context["request"]
        try:
            project = Project.objects.select_related("estimate").get(
                pk=attrs["project_id"], owner=request.user
            )
        except Project.DoesNotExist:
            raise serializers.ValidationError({"project_id": "Unknown project."}) from None
        if project.architect_id is None:
            raise serializers.ValidationError({"project_id": "Hire an architect first."})
        if hasattr(project, "engagement"):
            raise serializers.ValidationError({"project_id": "Engagement already exists."})
        attrs["project"] = project
        return attrs

    def create(self, validated_data):
        from decimal import Decimal

        project = validated_data["project"]
        kind = validated_data["kind"]

        total = None
        hourly_rate = None
        if kind == Engagement.Kind.FIXED:
            total = project.estimate.total if project.estimate else None
            if total is None:
                raise serializers.ValidationError("No estimate to derive the fixed quote from.")
        else:
            from apps.providers.models import ArchitectProfile

            profile = ArchitectProfile.objects.filter(user=project.architect).first()
            hourly_rate = profile.hourly_rate if profile else None
            if hourly_rate is None:
                raise serializers.ValidationError("Architect has no hourly rate configured.")

        # Locked business decision: the platform takes 0% of a project —
        # clients pay their architect directly. The FeePolicy singleton stays
        # authoritative (its default is 0), and the fallback matches it.
        fee_percent = Decimal("0")
        try:
            from apps.payments.models import FeePolicy

            fee_percent = FeePolicy.current_percent()
        except Exception:
            pass

        return Engagement.objects.create(
            project=project,
            client=project.owner,
            provider=project.architect,
            kind=kind,
            total=total,
            hourly_rate=hourly_rate,
            fee_percent=fee_percent,
            status=Engagement.Status.CONTRACTED,
        )


class RequoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequoteFlag
        fields = ["new_total", "reason"]
