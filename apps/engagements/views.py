from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Engagement, Milestone, RequoteFlag
from .serializers import (
    ChangeRequestSerializer,
    DeliverableSerializer,
    EngagementCreateSerializer,
    EngagementSerializer,
    MilestoneSerializer,
    RequoteCreateSerializer,
    RequoteFlagSerializer,
    TimeEntrySerializer,
)


def _my_engagements(user):
    return Engagement.objects.filter(Q(client=user) | Q(provider=user))


def _get_engagement(user, pk):
    return get_object_or_404(_my_engagements(user), pk=pk)


class EngagementListCreateView(generics.ListCreateAPIView):
    def get_serializer_class(self):
        return EngagementCreateSerializer if self.request.method == "POST" else EngagementSerializer

    def get_queryset(self):
        return (
            _my_engagements(self.request.user)
            .select_related("project")
            .prefetch_related("milestones")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        engagement = serializer.save()
        return Response(EngagementSerializer(engagement).data, status=status.HTTP_201_CREATED)


class EngagementDetailView(generics.RetrieveAPIView):
    serializer_class = EngagementSerializer

    def get_queryset(self):
        return (
            _my_engagements(self.request.user)
            .select_related("project")
            .prefetch_related("milestones")
        )


class MilestoneListCreateView(APIView):
    """Provider defines milestones; both parties read. Fixed-quote milestones must
    sum to the contract total before work can be funded."""

    def get(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        return Response(MilestoneSerializer(engagement.milestones.all(), many=True).data)

    def post(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        if request.user != engagement.provider:
            return Response(
                {"detail": "Only the provider defines milestones."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = MilestoneSerializer(data=request.data, many=isinstance(request.data, list))
        serializer.is_valid(raise_exception=True)
        engagement.milestones.all().delete()
        rows = serializer.validated_data
        if not isinstance(rows, list):
            rows = [rows]
        for order, row in enumerate(rows):
            Milestone.objects.create(engagement=engagement, sort_order=order, **row)
        try:
            engagement.validate_milestones_sum()
        except DjangoValidationError as exc:
            engagement.milestones.all().delete()
            return Response({"detail": exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            MilestoneSerializer(engagement.milestones.all(), many=True).data,
            status=status.HTTP_201_CREATED,
        )


class MilestoneActionView(APIView):
    """submit (provider) · approve (client) · request-changes (client, multipart)."""

    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, pk, action):
        milestone = get_object_or_404(Milestone.objects.select_related("engagement"), pk=pk)
        engagement = milestone.engagement
        if request.user not in (engagement.client, engagement.provider):
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            if action == "submit":
                if request.user != engagement.provider:
                    return Response(status=status.HTTP_403_FORBIDDEN)
                milestone.transition(Milestone.Status.IN_REVIEW)
            elif action == "approve":
                if request.user != engagement.client:
                    return Response(status=status.HTTP_403_FORBIDDEN)
                milestone.transition(Milestone.Status.DONE)
                self._on_approved(milestone)
            elif action == "request-changes":
                if request.user != engagement.client:
                    return Response(status=status.HTTP_403_FORBIDDEN)
                change_serializer = ChangeRequestSerializer(data=request.data)
                change_serializer.is_valid(raise_exception=True)
                milestone.transition(Milestone.Status.REVISING)
                change_serializer.save(milestone=milestone, requested_by=request.user)
            else:
                return Response(status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)

        return Response(MilestoneSerializer(milestone).data)

    @staticmethod
    def _on_approved(milestone):
        """Escrow release hook — wired to the payments ledger in Stage 9."""
        try:
            from apps.payments.services import release_milestone

            release_milestone(milestone)
        except ImportError:
            pass


class RequoteListCreateView(APIView):
    def get(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        return Response(RequoteFlagSerializer(engagement.requotes.all(), many=True).data)

    def post(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        if request.user != engagement.provider:
            return Response(
                {"detail": "Only the provider raises re-quotes."}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = RequoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requote = serializer.save(
            engagement=engagement, raised_by=request.user, old_total=engagement.total or 0
        )
        return Response(RequoteFlagSerializer(requote).data, status=status.HTTP_201_CREATED)


class RequoteResolveView(APIView):
    def post(self, request, pk, action):
        requote = get_object_or_404(RequoteFlag.objects.select_related("engagement"), pk=pk)
        if request.user != requote.engagement.client:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            requote.resolve(approve=(action == "approve"))
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=status.HTTP_409_CONFLICT)
        return Response(RequoteFlagSerializer(requote).data)


class TimeEntryListCreateView(APIView):
    def get(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        entries = engagement.time_entries.all()
        total_hours = sum(e.hours for e in entries)
        return Response(
            {
                "entries": TimeEntrySerializer(entries, many=True).data,
                "total_hours": str(total_hours),
            }
        )

    def post(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        if request.user != engagement.provider:
            return Response(
                {"detail": "Only the provider logs time."}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = TimeEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(engagement=engagement, provider=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DeliverableListCreateView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        return Response(
            DeliverableSerializer(
                engagement.deliverables.all(), many=True, context={"request": request}
            ).data
        )

    def post(self, request, pk):
        engagement = _get_engagement(request.user, pk)
        if request.user != engagement.provider:
            return Response(
                {"detail": "Only the provider uploads deliverables."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = DeliverableSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        upload = request.FILES.get("file")
        serializer.save(
            engagement=engagement,
            uploaded_by=request.user,
            size_bytes=upload.size if upload else 0,
            name=serializer.validated_data.get("name") or (upload.name if upload else "file"),
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
