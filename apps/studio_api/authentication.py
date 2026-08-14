"""Studio bearer-token authentication.

Deliberately not Clerk. Clerk identities are marketplace accounts — clients, architects,
experts — and the studio is the owner's tool; hanging site-editing rights off the same
credential would mean every Clerk misconfiguration became a content-integrity question.
The scheme name is `Studio` rather than `Bearer` so the two can never be confused by a
proxy, a log line, or `ClerkAuthentication` sharing a header.
"""

from rest_framework import authentication, exceptions

from .models import StudioSession, hash_token

SCHEME = "studio"


class StudioTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        scheme, _, raw = header.partition(" ")
        if scheme.lower() != SCHEME:
            return None
        raw = raw.strip()
        if not raw:
            raise exceptions.AuthenticationFailed("Studio token missing.")

        session = (
            StudioSession.objects.filter(token_hash=hash_token(raw)).select_related("user").first()
        )
        # One message for "no such token", "revoked" and "expired": which of the three it
        # is tells an attacker whether they guessed a real token.
        if session is None or not session.is_active:
            raise exceptions.AuthenticationFailed("Studio session is not valid.")
        if not (session.user.is_active and session.user.is_staff):
            # Staff was revoked after the session was issued.
            raise exceptions.AuthenticationFailed("Studio session is not valid.")

        session.touch()
        request.studio_session = session
        return (session.user, session)

    def authenticate_header(self, request):
        return "Studio"
