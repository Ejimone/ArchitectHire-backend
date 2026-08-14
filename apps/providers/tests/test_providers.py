import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from PIL import Image

from apps.accounts.factories import UserFactory
from apps.providers.models import ArchitectProfile, Credential, OnboardingStatus, Review
from apps.providers.serializers import MAX_UPLOAD_BYTES


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (120, 90, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions,providers")


@pytest.mark.django_db
class TestDisciplines:
    def test_public_list_with_gating_flags(self, seeded, api_client):
        body = api_client.get("/api/v1/providers/disciplines/").json()
        by_key = {d["key"]: d for d in body}
        assert len(by_key) >= 6
        assert by_key["structural-mep"]["requires_license"] is True
        assert by_key["cad-drafting"]["requires_license"] is False
        assert by_key["3d-scanning-bim"]["requires_onsite"] is True


@pytest.mark.django_db
class TestMyProfile:
    def test_requires_auth(self, api_client):
        assert api_client.get("/api/v1/providers/me/profile/").status_code == 401

    def test_architect_profile_created_and_patched(self, seeded, api_client):
        user = UserFactory(role="architect")
        api_client.force_authenticate(user=user)
        first = api_client.get("/api/v1/providers/me/profile/").json()
        assert first["onboarding_status"] == "in_progress"

        response = api_client.patch(
            "/api/v1/providers/me/profile/",
            {
                "firm_name": "Ellison Design Studio",
                "years_licensed": 12,
                "engagement_mode": "both",
                "hourly_rate": "135.00",
                "licensed_states": ["CA", "OR"],
                "stamp_jurisdictions": ["Oakland", "Alameda County"],
            },
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["firm_name"] == "Ellison Design Studio"
        assert sorted(body["licensed_states"]) == ["CA", "OR"]

    def test_expert_profile_role_aware(self, seeded, api_client):
        user = UserFactory(role="expert")
        api_client.force_authenticate(user=user)
        response = api_client.patch(
            "/api/v1/providers/me/profile/",
            {"disciplines": ["cad-drafting", "structural-mep"], "pricing_mode": "both"},
            format="json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["requires_license"] is True  # structural-mep gates licensure
        assert "studio_name" in body

    def test_submit_onboarding(self, seeded, api_client):
        user = UserFactory(role="architect")
        api_client.force_authenticate(user=user)
        api_client.get("/api/v1/providers/me/profile/")
        response = api_client.post("/api/v1/providers/me/submit/")
        assert response.status_code == 200
        assert response.json()["onboarding_status"] == "submitted"
        # Double submit conflicts
        assert api_client.post("/api/v1/providers/me/submit/").status_code == 409


@pytest.mark.django_db
class TestCredentials:
    def test_upload_and_state_machine(self, seeded, api_client):
        user = UserFactory(role="architect")
        staff = UserFactory(role="staff")
        api_client.force_authenticate(user=user)
        response = api_client.post(
            "/api/v1/providers/me/credentials/",
            {"kind": "architect_license", "issuing_state": "CA", "number": "C-38214"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["status"] == "uploaded"

        credential = Credential.objects.get(user=user)
        credential.verify(staff)
        assert credential.status == "verified"
        assert credential.verified_by == staff

    def test_an_oversize_document_is_refused(self, seeded, api_client):
        api_client.force_authenticate(user=UserFactory(role="architect"))
        response = api_client.post(
            "/api/v1/providers/me/credentials/",
            {
                "kind": "architect_license",
                "document": SimpleUploadedFile(
                    "license.pdf", b"%PDF-1.4" + b"0" * MAX_UPLOAD_BYTES, "application/pdf"
                ),
            },
            format="multipart",
        )
        assert response.status_code == 400
        assert "too large" in str(response.json()["document"])

    @pytest.mark.parametrize(
        ("name", "content_type"),
        [
            ("payload.exe", "application/x-msdownload"),
            ("payload.svg", "image/svg+xml"),
            # A real PDF wearing a name the storage layer would serve inline.
            ("payload.html", "application/pdf"),
            ("payload.pdf", "text/html"),
        ],
    )
    def test_only_allowlisted_document_types_are_accepted(
        self, seeded, api_client, name, content_type
    ):
        """The wizard checks this client-side too, but that is UX — this is the
        boundary that has to hold."""
        api_client.force_authenticate(user=UserFactory(role="architect"))
        response = api_client.post(
            "/api/v1/providers/me/credentials/",
            {
                "kind": "architect_license",
                "document": SimpleUploadedFile(name, b"%PDF-1.4 test", content_type),
            },
            format="multipart",
        )
        assert response.status_code == 400
        assert "Unsupported file type" in str(response.json()["document"])

    def test_a_pdf_licence_uploads(self, seeded, api_client):
        api_client.force_authenticate(user=UserFactory(role="architect"))
        response = api_client.post(
            "/api/v1/providers/me/credentials/",
            {
                "kind": "architect_license",
                "document": SimpleUploadedFile("license.PDF", b"%PDF-1.4 test", "application/pdf"),
            },
            format="multipart",
        )
        assert response.status_code == 201
        assert response.json()["document"].endswith(".PDF")

    def test_credentials_are_private_to_owner(self, seeded, api_client):
        owner = UserFactory(role="architect")
        Credential.objects.create(user=owner, kind="architect_license", number="C-1")
        other = UserFactory(role="architect")
        api_client.force_authenticate(user=other)
        body = api_client.get("/api/v1/providers/me/credentials/").json()
        assert body == []


@pytest.mark.django_db
class TestImageUploads:
    def test_portfolio_images_must_be_an_allowed_image(self, seeded, api_client):
        """Pillow proves the bytes are an image; the name still has to be one we
        are willing to hand back."""
        api_client.force_authenticate(user=UserFactory(role="architect"))
        response = api_client.post(
            "/api/v1/providers/me/portfolio/",
            {
                "title": "Backyard ADU",
                "image": SimpleUploadedFile("shot.gif", png_bytes(), "image/png"),
            },
            format="multipart",
        )
        assert response.status_code == 400
        assert "Unsupported file type" in str(response.json()["image"])

    def test_a_png_portfolio_image_uploads(self, seeded, api_client):
        api_client.force_authenticate(user=UserFactory(role="architect"))
        response = api_client.post(
            "/api/v1/providers/me/portfolio/",
            {
                "title": "Backyard ADU",
                "image": SimpleUploadedFile("shot.png", png_bytes(), "image/png"),
            },
            format="multipart",
        )
        assert response.status_code == 201

    def test_headshots_go_through_the_same_gate(self, seeded, api_client):
        api_client.force_authenticate(user=UserFactory(role="expert"))
        response = api_client.patch(
            "/api/v1/providers/me/profile/",
            {"headshot": SimpleUploadedFile("me.gif", png_bytes(), "image/png")},
            format="multipart",
        )
        assert response.status_code == 400
        assert "Unsupported file type" in str(response.json()["headshot"])


@pytest.mark.django_db
class TestPublicProfile:
    def test_only_live_profiles_visible(self, seeded, api_client):
        user = UserFactory(role="architect", first_name="Maya", last_name="Ellison")
        profile = ArchitectProfile.objects.create(user=user, firm_name="Studio M")
        assert api_client.get(f"/api/v1/providers/architects/{profile.pk}/").status_code == 404

        profile.onboarding_status = OnboardingStatus.APPROVED
        profile.save()
        Review.objects.create(
            provider=user, reviewer_name="Dana", reviewer_role="Homeowner · Berkeley, CA", rating=5
        )
        Credential.objects.create(
            user=user, kind="architect_license", number="C-38214", status="verified"
        )
        body = api_client.get(f"/api/v1/providers/architects/{profile.pk}/").json()
        assert body["name"] == "Maya Ellison"
        assert body["reviews"][0]["rating"] == 5
        assert any("license" in c["kind"].lower() for c in body["verified_credentials"])
