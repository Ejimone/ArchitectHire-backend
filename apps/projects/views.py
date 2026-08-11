from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.notifications.tasks import notify

from .models import Estimate, Match, Project
from .serializers import (
    EstimateCreateSerializer,
    EstimateSerializer,
    LeadSerializer,
    MatchSerializer,
    ProjectCreateSerializer,
    ProjectSerializer,
)


class EstimateCreateView(generics.CreateAPIView):
    """POST /api/v1/estimates/ — instant estimate; anonymous allowed (pre-signup funnel)."""

    serializer_class = EstimateCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "estimates"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        estimate = serializer.save()
        return Response(EstimateSerializer(estimate).data, status=201)


class EstimateDetailView(generics.RetrieveAPIView):
    """GET /api/v1/estimates/{uuid}/ — shareable estimate snapshot."""

    queryset = Estimate.objects.select_related("state")
    serializer_class = EstimateSerializer
    permission_classes = [AllowAny]


class ProjectListCreateView(generics.ListCreateAPIView):
    """GET: my projects. POST: claim an estimate → project + 2–3 matches."""

    def get_queryset(self):
        return (
            Project.objects.filter(owner=self.request.user)
            .select_related("state", "estimate__state")
            .prefetch_related("matches__architect")
        )

    def get_serializer_class(self):
        return ProjectCreateSerializer if self.request.method == "POST" else ProjectSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save()
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectDetailView(generics.RetrieveAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return (
            Project.objects.filter(owner=self.request.user)
            .select_related("state", "estimate__state")
            .prefetch_related("matches__architect")
        )


class ProjectMatchesView(generics.ListAPIView):
    serializer_class = MatchSerializer
    pagination_class = None

    def get_queryset(self):
        project = get_object_or_404(Project, pk=self.kwargs["pk"], owner=self.request.user)
        return project.matches.select_related("architect")


class HireView(APIView):
    """POST /api/v1/projects/{id}/hire/ {"match_id": n} — pick the architect."""

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk, owner=request.user)
        match = get_object_or_404(Match, pk=request.data.get("match_id"), project=project)
        if project.status != Project.Status.CHOOSING_ARCHITECT:
            return Response(
                {"detail": "Project already underway."}, status=status.HTTP_409_CONFLICT
            )
        match.status = Match.Status.HIRED
        match.save(update_fields=["status"])
        project.hire(match.architect)
        project.matches.exclude(pk=match.pk).update(status=Match.Status.WITHDRAWN)
        client_name = request.user.display_name
        transaction.on_commit(
            lambda: notify.delay(
                match.architect_id,
                "lead",
                f"You've been hired — {project.title}",
                f"{client_name} picked you. Time to scope the work.",
                {"project_id": project.pk},
            )
        )
        return Response(ProjectSerializer(project).data)


class MyLeadsView(generics.ListAPIView):
    """GET /api/v1/providers/me/leads/ — the architect's lead inbox."""

    serializer_class = LeadSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Match.objects.filter(architect=self.request.user)
            .exclude(status=Match.Status.WITHDRAWN)
            .select_related("project__estimate", "project__state")
        )


class LeadRespondView(APIView):
    """POST /api/v1/leads/{id}/accept|decline — undoable until hired."""

    def post(self, request, pk, action):
        match = get_object_or_404(
            Match.objects.select_related("project"), pk=pk, architect=request.user
        )
        try:
            match.respond(accept=(action == "accept"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        architect_name = request.user.display_name
        verb = "accepted" if action == "accept" else "declined"
        transaction.on_commit(
            lambda: notify.delay(
                match.project.owner_id,
                "system",
                f"{architect_name} {verb} your project",
                "",
                {"project_id": match.project_id},
            )
        )
        return Response(LeadSerializer(match).data)
