"""Provider model strings, credential rejection, portfolio writes and admin queues."""

import pytest
from django.contrib.admin.sites import site
from django.core.management import call_command

from apps.accounts.factories import UserFactory
from apps.accounts.models import User
from apps.jurisdictions.models import State
from apps.providers.admin import (
    ArchitectProfileAdmin,
    CredentialAdmin,
    CredentialInline,
    ExpertProfileAdmin,
)
from apps.providers.models import (
    ArchitectProfile,
    Credential,
    Discipline,
    ExpertProfile,
    OnboardingStatus,
    PortfolioItem,
    Review,
)
from apps.providers.serializers import StateCodesField


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,providers")


PROVIDER = User(email="maya@example.com")


@pytest.mark.parametrize(
    ("obj", "expected"),
    [
        (Discipline(name="CAD drafting"), "CAD drafting"),
        (ArchitectProfile(user=PROVIDER), "Architect: maya@example.com"),
        (ExpertProfile(user=PROVIDER), "Expert: maya@example.com"),
        (
            Credential(user=PROVIDER, kind="architect_license", status="uploaded"),
            "Architect license · maya@example.com · uploaded",
        ),
        (PortfolioItem(title="Backyard ADU"), "Backyard ADU"),
        (
            Review(provider=PROVIDER, reviewer_name="Dana", rating=5),
            "5/5 for maya@example.com by Dana",
        ),
    ],
)
def test_str(obj, expected):
    assert str(obj) == expected


def test_is_live_tracks_onboarding_status():
    assert ArchitectProfile(onboarding_status=OnboardingStatus.APPROVED).is_live is True
    assert ArchitectProfile(onboarding_status=OnboardingStatus.SUBMITTED).is_live is False


@pytest.mark.django_db
def test_state_codes_field_is_a_multi_slug_relation(seeded):
    field = StateCodesField()
    assert field.slug_field == "code"
    assert set(field.get_queryset()) == set(State.objects.all())


@pytest.mark.django_db
class TestCredentialReview:
    def test_rejection_records_the_reviewer_and_notes(self):
        provider = UserFactory(role="architect")
        staff = UserFactory(role="staff")
        credential = Credential.objects.create(
            user=provider, kind="architect_license", number="C-1"
        )

        credential.reject(staff, notes="License number does not match NCARB")
        credential.refresh_from_db()
        assert credential.status == Credential.Status.REJECTED
        assert credential.verified_by == staff
        assert credential.review_notes == "License number does not match NCARB"

    def test_rejection_without_notes_keeps_the_existing_note(self):
        provider = UserFactory(role="architect")
        staff = UserFactory(role="staff")
        credential = Credential.objects.create(user=provider, kind="w9", review_notes="Prior note")

        credential.reject(staff)
        credential.refresh_from_db()
        assert credential.status == Credential.Status.REJECTED
        assert credential.review_notes == "Prior note"


@pytest.mark.django_db
class TestPortfolio:
    def test_items_are_created_for_the_signed_in_provider(self, api_client):
        provider = UserFactory(role="architect")
        api_client.force_authenticate(user=provider)
        response = api_client.post(
            "/api/v1/providers/me/portfolio/",
            {"title": "Backyard ADU", "meta": "ADU · Oakland · 2025"},
            format="json",
        )
        assert response.status_code == 201
        assert PortfolioItem.objects.get(pk=response.json()["id"]).user == provider


@pytest.mark.django_db
class TestAdminQueues:
    def test_credentials_cannot_be_added_from_the_profile_inline(self):
        assert CredentialInline(ArchitectProfile, site).has_add_permission(None) is False

    def test_profile_inline_shows_that_users_credentials(self):
        """`Credential.user` points at User, not at the profile, so the inline has to
        bridge that hop itself — this is what makes it a nonrelated inline."""
        architect = ArchitectProfile.objects.create(user=UserFactory(role="architect"))
        other = ArchitectProfile.objects.create(user=UserFactory(role="architect"))
        mine = Credential.objects.create(user=architect.user, kind="license", number="A-1")
        Credential.objects.create(user=other.user, kind="license", number="B-2")

        queryset = CredentialInline(ArchitectProfile, site).get_form_queryset(architect)

        assert list(queryset) == [mine]

    def test_profile_inline_attaches_new_rows_to_the_profiles_user(self):
        architect = ArchitectProfile.objects.create(user=UserFactory(role="architect"))
        credential = Credential(kind="license", number="C-3")

        CredentialInline(ArchitectProfile, site).save_new_instance(architect, credential)

        assert credential.user == architect.user

    def test_approving_profiles_goes_live(self):
        architect = ArchitectProfile.objects.create(user=UserFactory(role="architect"))
        expert = ExpertProfile.objects.create(user=UserFactory(role="expert"))

        ArchitectProfileAdmin(ArchitectProfile, site).approve_selected(
            None, ArchitectProfile.objects.filter(pk=architect.pk)
        )
        ExpertProfileAdmin(ExpertProfile, site).approve_selected(
            None, ExpertProfile.objects.filter(pk=expert.pk)
        )

        architect.refresh_from_db()
        expert.refresh_from_db()
        assert architect.onboarding_status == OnboardingStatus.APPROVED
        assert architect.approved_at is not None
        assert expert.onboarding_status == OnboardingStatus.APPROVED

    def test_bulk_verify_and_reject_only_touch_uploaded_credentials(self):
        provider = UserFactory(role="architect")
        staff = UserFactory(role="staff")
        to_verify = Credential.objects.create(user=provider, kind="ncarb", number="N-1")
        to_reject = Credential.objects.create(user=provider, kind="w9")
        already_done = Credential.objects.create(
            user=provider, kind="eo_insurance", status=Credential.Status.VERIFIED
        )

        model_admin = CredentialAdmin(Credential, site)
        request = type("Request", (), {"user": staff})()

        model_admin.verify_selected(request, Credential.objects.filter(pk=to_verify.pk))
        model_admin.reject_selected(
            request, Credential.objects.filter(pk__in=[to_reject.pk, already_done.pk])
        )

        to_verify.refresh_from_db()
        to_reject.refresh_from_db()
        already_done.refresh_from_db()
        assert to_verify.status == Credential.Status.VERIFIED
        assert to_verify.verified_by == staff
        assert to_reject.status == Credential.Status.REJECTED
        assert already_done.status == Credential.Status.VERIFIED  # untouched
