import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

from apps.messaging.consumers import UserConsumer  # noqa: E402
from apps.messaging.middleware import ClerkAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": ClerkAuthMiddleware(URLRouter([path("ws/", UserConsumer.as_asgi())])),
    }
)
