"""Every registered admin page must render, and must render through Studio.

A theme swap touches all 73 registrations at once, so the useful guard is breadth:
walk the whole registry rather than spot-checking a few models. This catches the two
failure modes a reskin actually produces — a template that raises, and a ModelAdmin
that quietly fell back to the stock Django base and renders unstyled.
"""

import pytest
from django.contrib import admin
from django.urls import reverse

pytestmark = pytest.mark.django_db

# Present on every page Unfold renders; absent if a stock Django template was used.
UNFOLD_MARKER = "unfold/css/styles.css"


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        email="studio-admin@architecthire.test", password="studio-pass-12345"
    )
    client.force_login(user)
    return client


def registered_models():
    return sorted(admin.site._registry, key=lambda m: m._meta.label_lower)


def model_ids(model):
    return model._meta.label_lower


@pytest.mark.parametrize("model", registered_models(), ids=model_ids)
def test_changelist_renders_through_studio(staff_client, model):
    meta = model._meta
    url = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")

    response = staff_client.get(url, follow=True)

    assert response.status_code == 200, f"{meta.label} changelist returned {response.status_code}"
    assert UNFOLD_MARKER in response.content.decode(), f"{meta.label} changelist is unstyled"


@pytest.mark.parametrize("model", registered_models(), ids=model_ids)
def test_add_form_renders_through_studio(staff_client, model):
    meta = model._meta
    model_admin = admin.site._registry[model]
    if not model_admin.has_add_permission(_request_for(staff_client)):
        pytest.skip(f"{meta.label} is not addable")

    url = reverse(f"admin:{meta.app_label}_{meta.model_name}_add")

    response = staff_client.get(url, follow=True)

    assert response.status_code == 200, f"{meta.label} add form returned {response.status_code}"
    assert UNFOLD_MARKER in response.content.decode(), f"{meta.label} add form is unstyled"


def test_index_renders_through_studio(staff_client):
    response = staff_client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert UNFOLD_MARKER in response.content.decode()


def test_login_page_renders_through_studio(client):
    response = client.get(reverse("admin:login"))

    assert response.status_code == 200
    assert UNFOLD_MARKER in response.content.decode()


def test_admin_site_is_the_studio_site():
    from apps.studio.sites import StudioAdminSite

    assert isinstance(admin.site._wrapped, StudioAdminSite)


def _request_for(client):
    """A minimal request stand-in for permission checks that only read `user`."""
    from django.test import RequestFactory

    request = RequestFactory().get("/admin/")
    request.user = client.session and _session_user(client)
    return request


def _session_user(client):
    from django.contrib.auth import get_user
    from django.http import HttpRequest

    request = HttpRequest()
    request.session = client.session
    return get_user(request)
