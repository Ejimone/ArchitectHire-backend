"""Generate VAPID keys for Web Push:

uv run python -c "from apps.notifications.vapid import generate; generate()"
"""

import base64

from cryptography.hazmat.primitives.asymmetric import ec


def generate():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_numbers = private_key.public_key().public_numbers()
    public_bytes = (
        b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
    )
    encode = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()  # noqa: E731
    print(f"VAPID_PRIVATE_KEY={encode(private_value)}")  # noqa: T201
    print(f"VAPID_PUBLIC_KEY={encode(public_bytes)}")  # noqa: T201
