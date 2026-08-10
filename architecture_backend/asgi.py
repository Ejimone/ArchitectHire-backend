import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "architecture_backend.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter  # noqa: E402

# WebSocket routing (messaging consumers + JWT auth middleware) is wired in Stage 10.
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
    }
)
