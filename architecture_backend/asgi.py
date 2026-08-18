import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.urls import path  # noqa: E402

from apps.messaging.consumers import UserConsumer  # noqa: E402
from apps.messaging.middleware import ClerkAuthMiddleware  # noqa: E402
from apps.studio_api.consumers import StudioConsumer  # noqa: E402
from apps.studio_api.middleware import StudioTicketMiddleware  # noqa: E402


def websocket_application():
    """Origin check, then Clerk auth, then routing.

    OriginValidator and not AllowedHostsOriginValidator: the browser Origin is the
    frontend domain (https://architecthire.com) while ALLOWED_HOSTS holds the App
    Platform service hostname the socket terminates on, so matching one against the
    other would reject every legitimate production handshake.
    """
    return OriginValidator(
        URLRouter(
            [
                # The studio's socket authenticates with a ticket, not a Clerk JWT.
                path("ws/studio/", StudioTicketMiddleware(StudioConsumer.as_asgi())),
                path("ws/", ClerkAuthMiddleware(UserConsumer.as_asgi())),
            ]
        ),
        settings.WS_ALLOWED_ORIGINS,
    )


async def http_application(scope, receive, send):
    """Django, behind a health endpoint that cannot be starved by request traffic.

    `/healthz` answers on the event loop — before ALLOWED_HOSTS validation and before
    Django's single sync thread, both of which have taken the app down when a platform
    health prober met them: the prober's Host header is the container IP (DisallowedHost
    → 400), and under a request burst the sync queue starved the probe until the platform
    killed a perfectly healthy container.

    It used to return a literal 200 and nothing else, which meant the reverse was also
    true: a container whose connection pool had died — handing out dead connections so
    that every real request failed with PoolTimeout — still reported itself healthy and
    kept taking traffic. The probe now actually checks, on its own thread so it still
    cannot queue behind request work. See `apps.core.health`.

    `/api/health/` remains the fuller, human-facing check.
    """
    if scope["type"] == "http" and scope["path"] in ("/healthz", "/healthz/"):
        from apps.core.health import probe

        status, body = await probe()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")],
            }
        )
        await send({"type": "http.response.body", "body": body})
        return
    await django_asgi_app(scope, receive, send)


application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": websocket_application(),
    }
)
