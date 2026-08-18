"""Private files on the VM disk: signed, expiring URLs instead of presigned object URLs."""

import importlib
import os
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.signing import TimestampSigner

from apps.core import storages as storages_module
from apps.core.storages import (
    SignedLocalStorage,
    private_storage,
    sign_private_name,
    unsign_private_name,
)


@pytest.fixture
def signed_storage(tmp_path, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "private": {
            "BACKEND": "apps.core.storages.SignedLocalStorage",
            "OPTIONS": {"location": str(tmp_path)},
        },
    }
    # `django.core.files.storage.storages` caches instances; reset so the override applies.
    from django.core.files.storage import storages

    storages._storages = {}
    return storages["private"]


class TestSignedLocalStorage:
    def test_url_carries_a_token_that_names_the_file(self, signed_storage):
        assert isinstance(signed_storage, SignedLocalStorage)
        name = signed_storage.save("deliverables/plan.pdf", ContentFile(b"%PDF"))
        url = signed_storage.url(name)
        assert url.startswith("/api/v1/files/?t=")
        assert unsign_private_name(url.split("t=", 1)[1]) == name

    def test_forged_and_expired_tokens_are_rejected(self):
        assert unsign_private_name("nonsense") is None
        assert unsign_private_name(sign_private_name("a.pdf") + "x") is None
        old = TimestampSigner(salt="apps.core.storages.private-file").sign("a.pdf")
        # Rewrite the timestamp portion to something ancient: value:timestamp:sig — the
        # signature no longer matches, which is the same refusal an expired one gets.
        parts = old.split(":")
        parts[1] = "1"
        assert unsign_private_name(":".join(parts)) is None

    def test_an_expired_token_is_rejected(self, monkeypatch):
        token = sign_private_name("a.pdf")
        monkeypatch.setattr(storages_module, "PRIVATE_URL_MAX_AGE", -1)
        assert unsign_private_name(token) is None

    def test_private_storage_resolves_the_alias(self, signed_storage):
        assert isinstance(private_storage(), SignedLocalStorage)


@pytest.mark.django_db
class TestPrivateFileView:
    def test_a_valid_token_streams_the_file(self, signed_storage, api_client):
        name = signed_storage.save("deliverables/plan.pdf", ContentFile(b"%PDF-bytes"))
        response = api_client.get(signed_storage.url(name))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"%PDF-bytes"
        assert response["Cache-Control"] == "private, no-store"

    def test_a_bad_token_is_forbidden(self, signed_storage, api_client):
        assert api_client.get("/api/v1/files/?t=forged").status_code == 403
        assert api_client.get("/api/v1/files/").status_code == 403

    def test_a_missing_file_is_a_404(self, signed_storage, api_client):
        response = api_client.get(f"/api/v1/files/?t={sign_private_name('gone.pdf')}")
        assert response.status_code == 404


def _load_prod(monkeypatch, **env):
    """Import prod settings under a controlled environment; return the module."""
    base = {
        "SECRET_KEY": "x",
        "ALLOWED_HOSTS": "api.example.com",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "postgres://u:p@localhost:5433/x"),
    }
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_STORAGE_BUCKET_NAME",
        "AWS_S3_ENDPOINT_URL",
        "MEDIA_BACKEND",
        "MEDIA_URL",
        "MEDIA_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**base, **env}.items():
        monkeypatch.setenv(key, value)
    # `base` reads the AWS_* environment at import time and `prod` re-exports it, so both
    # modules have to be re-imported for the patched environment to be seen.
    sys.modules.pop("architecture_backend.settings.prod", None)
    sys.modules.pop("architecture_backend.settings.base", None)
    return importlib.import_module("architecture_backend.settings.prod")


class TestProdMediaModes:
    def test_local_mode_uses_the_disk_and_signed_private_files(self, monkeypatch):
        prod = _load_prod(
            monkeypatch,
            MEDIA_BACKEND="local",
            MEDIA_URL="https://api.example.com/media/",
            MEDIA_ROOT="/srv/media",
        )
        assert prod.STORAGES["default"]["OPTIONS"] == {
            "location": "/srv/media",
            "base_url": "https://api.example.com/media/",
        }
        assert prod.STORAGES["private"]["BACKEND"] == "apps.core.storages.SignedLocalStorage"

    def test_local_mode_requires_an_absolute_media_url(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="MEDIA_URL must be an absolute URL"):
            _load_prod(monkeypatch, MEDIA_BACKEND="local", MEDIA_URL="/media/")

    def test_s3_mode_refuses_to_boot_without_credentials(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="Object storage is required"):
            _load_prod(monkeypatch, MEDIA_BACKEND="s3")

    def test_s3_mode_with_credentials(self, monkeypatch):
        prod = _load_prod(
            monkeypatch,
            AWS_ACCESS_KEY_ID="k",
            AWS_SECRET_ACCESS_KEY="s",
            AWS_STORAGE_BUCKET_NAME="b",
            AWS_S3_ENDPOINT_URL="https://sfo3.digitaloceanspaces.com",
        )
        assert prod.STORAGES["default"]["BACKEND"] == "apps.core.storages.PublicMediaStorage"

    def test_an_unknown_mode_is_refused(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="MEDIA_BACKEND must be"):
            _load_prod(monkeypatch, MEDIA_BACKEND="ftp")
