"""Storage backends.

Two deployments, two shapes:

* **Object storage** (S3-compatible — DigitalOcean Spaces): `PublicMediaStorage` for CMS
  imagery served straight from the bucket/CDN, `PrivateMediaStorage` for deliverables and
  credential documents behind short-lived presigned URLs.
* **VM disk** (`MEDIA_BACKEND=local`): Django's `FileSystemStorage` for public media, with
  Caddy serving the directory at `MEDIA_URL`, and `SignedLocalStorage` for private files —
  the same "a URL that works for ten minutes" contract as a presigned URL, issued and
  verified by Django itself (`apps.core.views.private_file`).

`STORAGES["private"]` picks one of the private backends; models reach it through
`private_storage()` so the choice is made at runtime, not at import.
"""

from django.core.files.storage import FileSystemStorage
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.urls import reverse
from storages.backends.s3 import S3Storage


class PublicMediaStorage(S3Storage):
    location = "media"
    default_acl = "public-read"
    querystring_auth = False
    file_overwrite = False


class PrivateMediaStorage(S3Storage):
    location = "private"
    default_acl = "private"
    querystring_auth = True
    querystring_expire = 600  # 10 minutes
    file_overwrite = False
    custom_domain = False  # signed URLs must hit the bucket endpoint, not the CDN


#: How long a private-file URL stays valid. Matches `PrivateMediaStorage.querystring_expire`
#: so a deliverable link behaves the same on both deployments.
PRIVATE_URL_MAX_AGE = 600
_SIGNER_SALT = "apps.core.storages.private-file"


def sign_private_name(name: str) -> str:
    return TimestampSigner(salt=_SIGNER_SALT).sign(name)


def unsign_private_name(token: str) -> str | None:
    """The storage name a token was issued for, or None if it is forged or expired."""
    try:
        return TimestampSigner(salt=_SIGNER_SALT).unsign(token, max_age=PRIVATE_URL_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


class SignedLocalStorage(FileSystemStorage):
    """Private files on the local disk, reachable only through a signed, expiring URL.

    The directory is *not* under `MEDIA_ROOT` and Caddy never serves it; the only way to a
    byte is `GET /api/v1/files/?t=<token>`, where the token names the file and expires.
    That is the presigned-URL contract without an object store.
    """

    def url(self, name):
        return f"{reverse('core:private-file')}?t={sign_private_name(name)}"


def private_storage():
    """Callable storage for FileFields — resolves the 'private' STORAGES alias at runtime
    (local filesystem in dev, presigned Spaces or signed local files in prod)."""
    from django.core.files.storage import storages

    return storages["private"]
