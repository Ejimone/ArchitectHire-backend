from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.tasks import notify
from apps.projects.models import Match, Project

from .models import Message, Thread, ThreadParticipant
from .serializers import MessageSerializer, ThreadSerializer


def _my_threads(user):
    return Thread.objects.filter(participants__user=user).distinct()


class ThreadListCreateView(APIView):
    """GET: my inbox. POST {match_id} or {project_id}: get-or-create the conversation."""

    def get(self, request):
        threads = (
            _my_threads(request.user)
            .select_related("project", "order")
            .prefetch_related("participants__user")
        )
        return Response(ThreadSerializer(threads, many=True, context={"request": request}).data)

    def post(self, request):
        user = request.user
        project = None
        other = None

        if request.data.get("match_id"):
            match = get_object_or_404(
                Match.objects.select_related("project"), pk=request.data["match_id"]
            )
            if user not in (match.project.owner, match.architect):
                return Response(status=status.HTTP_404_NOT_FOUND)
            project = match.project
            other = match.architect if user == match.project.owner else match.project.owner
        elif request.data.get("project_id"):
            project = get_object_or_404(Project, pk=request.data["project_id"])
            if user == project.owner and project.architect:
                other = project.architect
            elif user == project.architect:
                other = project.owner
            else:
                return Response(status=status.HTTP_404_NOT_FOUND)
        else:
            return Response(
                {"detail": "Pass match_id or project_id."}, status=status.HTTP_400_BAD_REQUEST
            )

        thread = (
            Thread.objects.filter(project=project, participants__user=user)
            .filter(participants__user=other)
            .first()
        )
        if thread is None:
            thread = Thread.objects.create(project=project)
            ThreadParticipant.objects.create(thread=thread, user=user)
            ThreadParticipant.objects.create(thread=thread, user=other)
        return Response(
            ThreadSerializer(thread, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MessageListCreateView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, pk):
        thread = get_object_or_404(_my_threads(request.user), pk=pk)
        messages = thread.messages.select_related("sender")[:200]
        return Response(MessageSerializer(messages, many=True, context={"request": request}).data)

    def post(self, request, pk):
        thread = get_object_or_404(_my_threads(request.user), pk=pk)
        if thread.archived:
            return Response({"detail": "Thread is archived."}, status=status.HTTP_409_CONFLICT)

        body = (request.data.get("body") or "").strip()
        upload = request.FILES.get("file")
        if not body and not upload:
            return Response({"detail": "Empty message."}, status=status.HTTP_400_BAD_REQUEST)

        if body and thread.contact_gated:
            body = Message.redact_contact_details(body)

        message = Message.objects.create(
            thread=thread,
            sender=request.user,
            kind=Message.Kind.FILE if upload else Message.Kind.TEXT,
            body=body,
            file=upload,
            file_name=upload.name if upload else "",
            file_size=upload.size if upload else 0,
        )
        thread.updated_at = timezone.now()
        thread.save(update_fields=["updated_at"])

        payload = MessageSerializer(message, context={"request": request}).data
        transaction.on_commit(lambda: self._fanout(thread, request.user, payload, message))
        return Response(payload, status=status.HTTP_201_CREATED)

    @staticmethod
    def _fanout(thread, sender, payload, message):
        channel_layer = get_channel_layer()
        preview = message.body[:80] or message.file_name or "New message"

        def push(user_id, mine):
            # `payload` was serialized in the sender's request context, so its
            # is_mine is True — override per recipient or every received
            # message renders on the wrong side of the chat.
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                {
                    "type": "relay",
                    "event": {
                        "type": "message.new",
                        "thread_id": thread.pk,
                        "message": {**payload, "is_mine": mine},
                    },
                },
            )

        if channel_layer is not None:
            # Echo to the sender's own group so a second tab stays live;
            # clients dedup by message id.
            push(sender.pk, True)
        for other in thread.other_participants(sender):
            if channel_layer is not None:
                push(other.pk, False)
            notify.delay(
                other.pk,
                "new_message",
                f"New message from {sender.display_name}",
                preview,
                {"thread_id": thread.pk},
            )


class ThreadReadView(APIView):
    def post(self, request, pk):
        updated = ThreadParticipant.objects.filter(thread_id=pk, user=request.user).update(
            last_read_at=timezone.now()
        )
        if not updated:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({"status": "read"})


class ScheduleCallView(APIView):
    """POST {call_time} — schedules a video call as a message (design: 'Video call scheduled')."""

    def post(self, request, pk):
        thread = get_object_or_404(_my_threads(request.user), pk=pk)
        call_time = request.data.get("call_time")
        if not call_time:
            return Response({"detail": "call_time required."}, status=status.HTTP_400_BAD_REQUEST)
        message = Message.objects.create(
            thread=thread,
            sender=request.user,
            kind=Message.Kind.CALL,
            body="Video call scheduled",
            call_time=call_time,
        )
        return Response(
            MessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
