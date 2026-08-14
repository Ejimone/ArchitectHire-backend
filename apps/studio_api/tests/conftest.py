import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.factories import UserFactory
from apps.studio_api.models import StudioSession

PASSWORD = "studio-pass-123"


@pytest.fixture
def staff_user(db):
    user = UserFactory(email="studio-owner@example.com", role="staff", is_staff=True)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def studio_token(staff_user):
    _session, token = StudioSession.issue(staff_user)
    return token


@pytest.fixture
def studio_client(api_client, studio_token):
    api_client.credentials(HTTP_AUTHORIZATION=f"Studio {studio_token}")
    return api_client


@pytest.fixture
def image_upload():
    """A real (tiny) PNG — ImageField validation rejects arbitrary bytes."""
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (30, 90, 200)).save(buffer, format="PNG")
    return SimpleUploadedFile("hero.png", buffer.getvalue(), content_type="image/png")
