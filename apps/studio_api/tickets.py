"""Short-lived tickets for the two paths where the browser must reach Django directly.

The studio's session token lives in an httpOnly cookie and only ever travels through the
studio's own server (the BFF proxy). Two things cannot go through that proxy: a large
image upload (Vercel caps function request bodies at 4.5 MB) and the WebSocket. For those
the proxy mints a *ticket* — a signed, purpose-bound, minutes-long derivative of the
session — and the browser presents that instead. A leaked ticket is worth one upload
window or one socket handshake, never the session.
"""

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

from .models import StudioSession

#: purpose → lifetime in seconds. Upload tickets outlive a slow connection on a big
#: photograph; a WebSocket ticket only has to survive the handshake.
PURPOSES = {"upload": 600, "ws": 60}


def issue_ticket(session: StudioSession, purpose: str) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"Unknown ticket purpose {purpose!r}.")
    return TimestampSigner(salt=f"studio-ticket:{purpose}").sign_object({"sid": session.pk})


def redeem_ticket(raw: str, purpose: str) -> StudioSession | None:
    """The live session a ticket stands for, or None if it is forged, expired, for a
    different purpose, or its session has since been revoked."""
    lifetime = PURPOSES.get(purpose)
    if not raw or lifetime is None:
        return None
    try:
        payload = TimestampSigner(salt=f"studio-ticket:{purpose}").unsign_object(
            raw, max_age=lifetime
        )
    except (BadSignature, SignatureExpired):
        return None
    session = StudioSession.objects.filter(pk=payload.get("sid")).select_related("user").first()
    if session is None or not session.is_active:
        return None
    if not (session.user.is_active and session.user.is_staff):
        return None
    return session
