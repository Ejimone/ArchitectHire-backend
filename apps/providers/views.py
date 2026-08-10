from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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


class MyCredentialsView(generics.ListCreateAPIView):
    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return Credential.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MyCredentialDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = CredentialSerializer
    permission_classes = [IsAuthenticated]

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
