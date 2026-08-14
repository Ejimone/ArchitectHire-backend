from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.engagements.models import Milestone
from apps.messaging.models import Message

from .models import (
    ArchitectProfile,
    Credential,
    Discipline,
    ExpertProfile,
    OnboardingStatus,
    PortfolioItem,
)
from .serializers import (
    ArchitectProfileSerializer,
    CredentialSerializer,
    DisciplineSerializer,
    ExpertProfileSerializer,
    PortfolioItemSerializer,
    PublicArchitectSerializer,
)

AGENDA_DEFAULT_DAYS = 21
AGENDA_MIN_DAYS = 1
AGENDA_MAX_DAYS = 90


def _profile_for(user):
    """Resolve (profile, serializer_class) from the user's role."""
    if user.role == "expert":
        profile, _ = ExpertProfile.objects.get_or_create(user=user)
        return profile, ExpertProfileSerializer
    profile, _ = ArchitectProfile.objects.get_or_create(user=user)
    return profile, ArchitectProfileSerializer


class DisciplinesView(generics.ListAPIView):
    """Public: the 6 expert disciplines with licensure gating flags."""

    queryset = Discipline.objects.all()
    serializer_class = DisciplineSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None


class MyProfileView(APIView):
    """GET/PATCH /api/v1/providers/me/profile/ — role-aware (architect or expert)."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        profile, serializer_class = _profile_for(request.user)
        return Response(serializer_class(profile, context={"request": request}).data)

    def patch(self, request):
        profile, serializer_class = _profile_for(request.user)
        serializer = serializer_class(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class SubmitOnboardingView(APIView):
    """POST /api/v1/providers/me/submit/ — finish the wizard, enter review."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile, serializer_class = _profile_for(request.user)
        if profile.onboarding_status not in (
            OnboardingStatus.IN_PROGRESS,
            OnboardingStatus.REJECTED,
        ):
            return Response(
                {"detail": f"Already {profile.get_onboarding_status_display()}."},
                status=status.HTTP_409_CONFLICT,
            )
        profile.submit()
        return Response(serializer_class(profile, context={"request": request}).data)


class MyAgendaView(APIView):
    """GET /api/v1/providers/me/agenda/?days=21 — what is coming up, flattened.

    The dashboard used to rebuild this client-side by pulling the full history of
    its six most recent threads and scanning them for calls: six requests, and a
    call booked in any quieter conversation never showed at all. One query for the
    calls, one for the deadlines, and the whole inbox is in scope.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = self._days(request.query_params.get("days"))
        now = timezone.now()
        horizon = now + timedelta(days=days)
        items = self._calls(request.user, now, horizon)
        items += self._deadlines(request.user, now.date(), horizon.date())
        items.sort(key=lambda item: item[0])
        return Response([item[1] for item in items])

    @staticmethod
    def _days(raw):
        try:
            days = int(raw)
        except (TypeError, ValueError):
            days = AGENDA_DEFAULT_DAYS
        return max(AGENDA_MIN_DAYS, min(days, AGENDA_MAX_DAYS))

    @staticmethod
    def _calls(user, now, horizon):
        messages = (
            Message.objects.filter(
                thread__participants__user=user,
                kind=Message.Kind.CALL,
                call_time__gte=now,
                call_time__lte=horizon,
            )
            .select_related("thread")
            .prefetch_related("thread__participants__user")
        )
        rows = []
        for message in messages:
            # Straight off the prefetch — `Thread.other_participants` would
            # re-query per message.
            others = [p.user for p in message.thread.participants.all() if p.user_id != user.pk]
            title = " · ".join(
                part
                for part in (message.body or "Call", others[0].display_name if others else "")
                if part
            )
            rows.append(
                (message.call_time, {"date": message.call_time, "title": title, "kind": "call"})
            )
        return rows

    @staticmethod
    def _deadlines(user, today, last_day):
        milestones = (
            Milestone.objects.filter(
                Q(engagement__client=user) | Q(engagement__provider=user),
                due_date__gte=today,
                due_date__lte=last_day,
            )
            .exclude(status=Milestone.Status.DONE)
            .select_related("engagement__project")
        )
        zone = timezone.get_current_timezone()
        return [
            (
                datetime.combine(milestone.due_date, time.min, tzinfo=zone),
                {
                    "date": milestone.due_date,
                    "title": f"{milestone.title} · {milestone.engagement.project.title}",
                    "kind": "deadline",
                },
            )
            for milestone in milestones
        ]


class MyCredentialsView(generics.ListCreateAPIView):
    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return Credential.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MyCredentialDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Updatable, and multipart-capable.

    The onboarding wizard uploads a document the moment the file is chosen, then PATCHes
    the typed metadata (number, expiry, issuing state) onto that row when the step is
    submitted — so the metadata write is inherently an update, and re-uploading a
    document sends multipart back to this same endpoint.
    """

    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return Credential.objects.filter(user=self.request.user)


class MyPortfolioView(generics.ListCreateAPIView):
    serializer_class = PortfolioItemSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return PortfolioItem.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MyPortfolioItemView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PortfolioItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PortfolioItem.objects.filter(user=self.request.user)


class PublicArchitectView(generics.RetrieveAPIView):
    """Public architect profile — live providers only."""

    serializer_class = PublicArchitectSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "pk"

    def get_queryset(self):
        return ArchitectProfile.objects.filter(
            onboarding_status=OnboardingStatus.APPROVED
        ).select_related("user")
