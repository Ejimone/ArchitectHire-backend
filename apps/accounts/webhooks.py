"""Clerk webhook receiver — keeps local users in sync with Clerk.

Clerk signs webhooks with svix. We verify the signature, then apply
user.created / user.updated / user.deleted to the local User table.
Deletion deactivates rather than deletes, preserving marketplace history.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from svix.webhooks import Webhook, WebhookVerificationError

logger = logging.getLogger(__name__)


def _primary_email(data: dict) -> str:
    primary_id = data.get("primary_email_address_id")
    for entry in data.get("email_addresses") or []:
        if entry.get("id") == primary_id:
            return entry.get("email_address", "")
    entries = data.get("email_addresses") or []
    return entries[0].get("email_address", "") if entries else ""


class ClerkWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        secret = settings.CLERK_WEBHOOK_SIGNING_SECRET
        if not secret:
            logger.error("CLERK_WEBHOOK_SIGNING_SECRET not configured; rejecting webhook")
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            event = Webhook(secret).verify(request.body, dict(request.headers))
        except (WebhookVerificationError, ValueError, KeyError):
            # svix raises binascii.Error (a ValueError) on malformed signature material
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get("type", "")
        data = event.get("data", {})
        handler = {
            "user.created": self._upsert_user,
            "user.updated": self._upsert_user,
            "user.deleted": self._deactivate_user,
        }.get(event_type)
        if handler:
            handler(data)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _upsert_user(data: dict):
        User = get_user_model()
        clerk_id = data.get("id")
        if not clerk_id:
            return
        email = _primary_email(data)
        fields = {
            "first_name": data.get("first_name") or "",
            "last_name": data.get("last_name") or "",
            "avatar_url": data.get("image_url") or "",
        }

        user = User.objects.filter(clerk_id=clerk_id).first()
        if user is None and email:
            # JIT-provisioned or pre-existing account under the same email.
            user = User.objects.filter(email__iexact=email).first()

        if user is None:
            if not email:
                logger.warning("Clerk user %s has no email; skipping create", clerk_id)
                return
            User.objects.create(clerk_id=clerk_id, email=email, **fields)
            return

        user.clerk_id = clerk_id
        if email:
            user.email = email
        for attr, value in fields.items():
            setattr(user, attr, value)
        user.save(update_fields=["clerk_id", "email", *fields.keys()])

    @staticmethod
    def _deactivate_user(data: dict):
        User = get_user_model()
        clerk_id = data.get("id")
        if clerk_id:
            User.objects.filter(clerk_id=clerk_id).update(is_active=False)
