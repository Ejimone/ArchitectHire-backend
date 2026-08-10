"""DigitalOcean Spaces (S3-compatible) storage backends.

Public: CMS imagery served via CDN, no signed querystrings.
Private: deliverables & credential documents, short-lived presigned URLs.
"""

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


def private_storage():
    """Callable storage for FileFields — resolves the 'private' STORAGES alias at runtime
    (local filesystem in dev, presigned DO Spaces in prod)."""
    from django.core.files.storage import storages

    return storages["private"]
