"""Pull a user's real profile from Clerk's Backend API.

Session JWTs carry only `sub` unless the owner customises the Clerk JWT
template, so a just-provisioned user has a synthetic pending email and no name.
In production the user.created webhook backfills it, but a local machine has no
tunnel for webhooks — and until the backfill lands, the UI would have nothing
human to show. This closes that gap at provisioning time.

Fail-soft by design: authentication must not depend on Clerk's API being up.
"""

import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"
# Clerk's API answers 403 to requests without a User-Agent.
USER_AGENT = "architecthire-backend"
TIMEOUT_SECONDS = 6


def fetch_clerk_profile(clerk_id: str) -> dict | None:
    """The Clerk user record, or None when unavailable for any reason."""
    if not settings.CLERK_SECRET_KEY:
        return None
    request = urllib.request.Request(
        f"{CLERK_API_BASE}/users/{clerk_id}",
        headers={
            "Authorization": f"Bearer {settings.CLERK_SECRET_KEY}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except Exception:  # noqa: BLE001 — auth must survive any Clerk API failure
        logger.warning("Could not fetch Clerk profile for %s", clerk_id, exc_info=True)
        return None


def apply_clerk_profile(user, profile: dict) -> list[str]:
    """Fill the user's blanks from a Clerk record; returns the fields changed."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    emails = {e["id"]: e["email_address"] for e in profile.get("email_addresses", [])}
    primary = emails.get(profile.get("primary_email_address_id")) or next(
        iter(emails.values()), ""
    )

    changed: list[str] = []
    if (
        user.has_placeholder_email
        and primary
        and not User.objects.filter(email=primary).exclude(pk=user.pk).exists()
    ):
        user.email = primary
        changed.append("email")
    if not user.first_name and profile.get("first_name"):
        user.first_name = profile["first_name"]
        changed.append("first_name")
    if not user.last_name and profile.get("last_name"):
        user.last_name = profile["last_name"]
        changed.append("last_name")
    if not user.avatar_url and profile.get("image_url"):
        user.avatar_url = profile["image_url"]
        changed.append("avatar_url")
    if changed:
        user.save(update_fields=changed)
    return changed


def backfill_user(user) -> list[str]:
    """Fetch + apply in one step. No-op unless the row is missing basics."""
    if not (user.has_placeholder_email or not user.first_name):
        return []
    profile = fetch_clerk_profile(user.clerk_id)
    if profile is None:
        return []
    return apply_clerk_profile(user, profile)
