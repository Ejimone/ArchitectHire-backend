from django.urls import path

from .views import (
    DisciplinesView,
    MyAgendaView,
    MyCredentialDetailView,
    MyCredentialsView,
    MyPortfolioItemView,
    MyPortfolioView,
    MyProfileView,
    PublicArchitectView,
    SubmitOnboardingView,
)

app_name = "providers"

urlpatterns = [
    path("disciplines/", DisciplinesView.as_view(), name="disciplines"),
    path("me/profile/", MyProfileView.as_view(), name="my-profile"),
    path("me/submit/", SubmitOnboardingView.as_view(), name="submit-onboarding"),
    path("me/agenda/", MyAgendaView.as_view(), name="my-agenda"),
    path("me/credentials/", MyCredentialsView.as_view(), name="my-credentials"),
    path("me/credentials/<int:pk>/", MyCredentialDetailView.as_view(), name="my-credential"),
    path("me/portfolio/", MyPortfolioView.as_view(), name="my-portfolio"),
    path("me/portfolio/<int:pk>/", MyPortfolioItemView.as_view(), name="my-portfolio-item"),
    path("architects/<int:pk>/", PublicArchitectView.as_view(), name="architect-detail"),
]
