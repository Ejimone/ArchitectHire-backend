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


def websocket_application():
    """Origin check, then Clerk auth, then routing.

    OriginValidator and not AllowedHostsOriginValidator: the browser Origin is the
    frontend domain (https://architecthire.com) while ALLOWED_HOSTS holds the App
    Platform service hostname the socket terminates on, so matching one against the
    other would reject every legitimate production handshake.
    """
    return OriginValidator(
        ClerkAuthMiddleware(URLRouter([path("ws/", UserConsumer.as_asgi())])),
        settings.WS_ALLOWED_ORIGINS,
    )


async def http_application(scope, receive, send):
    """Django, behind an instant liveness endpoint.

    `/healthz` answers on the event loop itself — before ALLOWED_HOSTS validation and
    before Django's single sync thread, both of which have taken the app down when a
    platform health prober met them: the prober's Host header is the container IP
    (DisallowedHost → 400), and under a request burst the sync queue starved the probe
    until the platform killed a perfectly healthy container. Point HTTP health checks
    here; `/api/health/` remains the deep check (database round trip) for humans.
    """
    if scope["type"] == "http" and scope["path"] in ("/healthz", "/healthz/"):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})
        return
    await django_asgi_app(scope, receive, send)


application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": websocket_application(),
    }
)
