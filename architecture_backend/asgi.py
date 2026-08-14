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


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": websocket_application(),
    }
)
