"""The JSON API the visual Studio talks to.

Every view here is staff-only and uncached. The public content API next door
(`apps.cms.views`) stays exactly as it was: this app reads through `compose_page` and
writes through `apps.cms` models, so there is no second definition of what a page is.
"""

import hashlib
import json
from functools import lru_cache

from django.contrib.auth import authenticate
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import Count
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cms.compose import BLOCK_KEY_BY_LABEL, BLOCK_MODELS, compose_page
from apps.cms.models import CopyBlock, MediaAsset, PageSEO
from apps.cms.slots import expected_media_slots, sync_media_slots
from apps.core.images import ProcessedImageField, process_image
from apps.core.revalidate import ping_now, schedule_warm
from apps.core.scopes import is_valid_scope, validate_slot_key
from apps.studio.pages import all_pages, route_for

from . import drafts as engine
from .authentication import StudioTokenAuthentication, StudioUploadTicketAuthentication
from .drafts import CHROME_MODELS, DraftError
from .events import actor, emit
from .fields import field_schema, snapshot
from .models import ContentDraft, ContentRevision, StudioSession
from .permissions import IsStudioStaff
from .registry import BY_LABEL, SPECS
from .tickets import PURPOSES, issue_ticket
from .uploads import UploadRejected, validate_upload

DRAFT = "draft"
LIVE = "live"


class StudioView(APIView):
    """Base: studio token only, staff only, no cache."""

    authentication_classes = [StudioTokenAuthentication]
    permission_classes = [IsStudioStaff]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    # Its own bucket, well above the default `user` rate. One canvas render is 4
    # authenticated calls and every save triggers a full refresh, so ordinary editing —
    # a few edits a minute — runs into 120/min in a couple of minutes and starts
    # returning 429s to the one person the tool exists for. The limit still exists;
    # it is set for an editor at a keyboard rather than for a public API client.
    throttle_scope = "studio"

    def handle_exception(self, exc):
        if isinstance(exc, DraftError):
            body = {"detail": str(exc)}
            if exc.errors:
                body["errors"] = exc.errors
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, UploadRejected):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)

    def page_number(self, default_size: int = 50, max_size: int = 200) -> tuple[int, int]:
        """`(page, page_size)` from the query string, clamped."""

        def as_int(name, fallback):
            try:
                return int(self.request.query_params.get(name, fallback))
            except (TypeError, ValueError):
                return fallback

        page = max(1, as_int("page", 1))
        size = min(max_size, max(1, as_int("page_size", default_size)))
        return page, size

    @property
    def mode(self) -> str:
        """`draft` stages the edit; `live` writes it straight to the site. Chosen by the
        editor in the toolbar and sent per request, so the two never get out of step."""
        return LIVE if self.request.query_params.get("mode") == LIVE else DRAFT

    def body(self) -> dict:
        """The request body as a plain dict. `request.data` is a QueryDict for multipart
        and form posts, where `dict()` would wrap every value in a list."""
        data = self.request.data
        return {key: data[key] for key in data}

    def write(self, *, model_label, op, object_id=None, payload=None):
        """Apply an edit in whichever mode this request asked for."""
        if self.mode == LIVE:
            change, revision = engine.apply_now(
                model_label=model_label,
                op=op,
                object_id=object_id,
                payload=payload,
                user=self.request.user,
            )
            self.announce(
                scope=revision.scope, model=model_label, object_id=change["object_id"], op=op
            )
            return Response(
                {"mode": LIVE, "object_id": change["object_id"], "revision": revision.pk}
            )

        # A pending create is addressed by the negative of its draft id; editing one has
        # to reach the draft, not a row that does not exist.
        if object_id is not None and object_id < 0:
            draft = engine.draft_for_canvas_id(model_label, object_id)
            if draft is None:
                raise DraftError(f"No pending row {model_label}:{object_id}.")
            if op == ContentDraft.Op.DELETE:
                scope = draft.scope
                draft.delete()
                self.announce(scope=scope, model=model_label, object_id=object_id, op="discarded")
                return Response({"mode": DRAFT, "object_id": object_id, "op": "discarded"})
            draft = engine.stage_create_edit(draft, payload or {})
        else:
            draft = engine.stage(
                model_label=model_label,
                op=op,
                object_id=object_id,
                payload=payload,
                user=self.request.user,
            )
        self.announce(scope=draft.scope, model=model_label, object_id=draft.canvas_id, op=draft.op)
        return Response({"mode": DRAFT, "object_id": draft.canvas_id, "op": draft.op})

    def announce(self, **fields):
        """Tell the other editors. `client` lets the originating tab ignore its own echo."""
        emit({"type": "draft.changed", "mode": self.mode, **fields, **actor(self.request)})


# ------------------------------------------------------------------------------- auth


class LoginView(APIView):
    """Studio sign-in. Staff password, not Clerk — see `authentication.py`."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "studio-login"

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        user = authenticate(request, username=email, password=password)
        # Same response for a bad password and for a valid non-staff account: the studio
        # login must not tell a marketplace user whether their address is a staff one.
        if user is None or not (user.is_active and user.is_staff):
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        session, token = StudioSession.issue(user)
        return Response(
            {
                "token": token,
                "expires_at": session.expires_at,
                "user": {"id": user.pk, "email": user.email, "name": user.display_name},
            }
        )


class LogoutView(StudioView):
    def post(self, request):
        request.auth.revoke()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(StudioView):
    def get(self, request):
        return Response(
            {
                "id": request.user.pk,
                "email": request.user.email,
                "name": request.user.display_name,
                "expires_at": request.auth.expires_at,
            }
        )


class TicketView(StudioView):
    """Mint a short-lived, purpose-bound ticket for the browser's two direct paths to
    Django: large uploads and the WebSocket. See `tickets.py`."""

    def post(self, request):
        purpose = request.data.get("purpose") or ""
        if purpose not in PURPOSES:
            return Response(
                {"detail": f"purpose must be one of {sorted(PURPOSES)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "ticket": issue_ticket(request.auth, purpose),
                "purpose": purpose,
                "expires_in": PURPOSES[purpose],
            }
        )


# ------------------------------------------------------------------------------ pages


class PageListView(StudioView):
    """The page tree, grouped the way the owner thinks about the site.

    Sections, labels and routes come from `apps.studio.pages`, which derives them from
    `apps.core.scopes` — so the Studio can never offer a page the content API would 404.
    """

    def get(self, request):
        pending = {
            row["scope"]: row["n"]
            for row in ContentDraft.objects.values("scope").annotate(n=Count("id"))
        }

        sections = {}
        for ref in all_pages():
            sections.setdefault(ref.section, []).append(
                {
                    "key": ref.key,
                    "label": ref.label,
                    "route": ref.route,
                    "subtitle": ref.subtitle,
                    # A page is editable when it can be previewed at a public URL, or when
                    # it is a record (a service, a blog post) the Studio edits as a form.
                    "editable": ref.route is not None or ref.record is not None,
                    "record": (
                        {"model": ref.record[0], "id": ref.record[1]} if ref.record else None
                    ),
                    "pending": pending.get(ref.key, 0),
                }
            )
        return Response(
            {
                "sections": [{"section": name, "pages": pages} for name, pages in sections.items()],
                "pending_total": sum(pending.values()),
            }
        )


class PageDetailView(StudioView):
    """The payload the canvas renders.

    Identical in shape to `GET /api/v1/content/pages/<key>/` — that identity is the whole
    point, because the Studio feeds it to the site's own components. In draft mode it
    additionally carries `pending` (rows with unpublished edits) and `_edit` (how to
    address each field), both of which the site simply ignores.
    """

    def get(self, request, page_key=None):
        if not is_valid_scope(page_key):
            return Response({"detail": "Unknown page."}, status=status.HTTP_404_NOT_FOUND)

        include_unpublished = self.mode == DRAFT
        payload = compose_page(page_key, request, include_unpublished=include_unpublished)
        if include_unpublished:
            payload = engine.overlay(payload, page_key, request)
        else:
            payload["pending"] = {}
        payload["_edit"] = self._edit_map(page_key, payload)
        payload["route"] = route_for(page_key)
        return Response(payload)

    def _edit_map(self, page_key, payload):
        """Where each part of the payload came from, so a click on the canvas resolves to
        a row without the client hard-coding the content model."""
        copy_ids = dict(CopyBlock.objects.filter(scope=page_key).values_list("key", "id"))
        rows = {
            asset.slot_key: asset
            for asset in MediaAsset.objects.filter(slot_key__startswith=f"{page_key}:")
        }
        seo = PageSEO.objects.filter(page_key=page_key).values_list("id", flat=True).first()

        # Every slot the page *could* show, filled or not. `compose_page` (rightly) omits
        # empty slots from the public payload, but the one image an editor most wants to
        # click is the one that has no picture yet — so the inventory travels here, and the
        # canvas merges it under the payload's media map. Rows the inventory does not know
        # (a slot the frontend added ahead of `sync_media_slots`) are listed too.
        slots = {}
        for slot_key, notes in expected_media_slots(page_key):
            slots[slot_key] = {"slot_key": slot_key, "notes": notes}
        for slot_key, asset in rows.items():
            slots.setdefault(slot_key, {"slot_key": slot_key, "notes": asset.notes})
        for slot_key, entry in slots.items():
            asset = rows.get(slot_key)
            entry.update(
                {
                    "id": asset.pk if asset else None,
                    "alt_text": asset.alt_text if asset else "",
                    "filled": bool(asset and asset.image),
                    "focal_x": asset.focal_x if asset else 0.5,
                    "focal_y": asset.focal_y if asset else 0.5,
                }
            )

        return {
            "scope": page_key,
            "mode": self.mode,
            "copy": {
                key: {"model": "cms.copyblock", "id": copy_ids.get(key)} for key in payload["copy"]
            },
            "blocks": {
                BLOCK_KEY_BY_LABEL[label]: {"model": label}
                for label in BLOCK_MODELS
                if BLOCK_KEY_BY_LABEL[label] in payload["blocks"]
            },
            "media": {
                slot: {
                    "model": "cms.mediaasset",
                    "id": rows[slot].pk if slot in rows else None,
                }
                for slot in payload["media"]
            },
            "slots": sorted(slots.values(), key=lambda entry: entry["slot_key"]),
            "seo": {"model": "cms.pageseo", "id": seo},
        }


@lru_cache(maxsize=1)
def build_schema() -> dict:
    """The schema is a function of the model definitions alone, so it is built once per
    process. `version` lets a client notice a deploy changed it."""
    labels = list(BLOCK_MODELS) + CHROME_MODELS
    models_ = {
        label: {
            "collection": BLOCK_KEY_BY_LABEL.get(label),
            "verbose_name": str(engine.resolve_model(label)._meta.verbose_name).capitalize(),
            "fields": field_schema(engine.resolve_model(label)),
        }
        for label in labels
    }
    # Collections (registry.py) carry the extra facts a generic record form needs.
    for spec in SPECS:
        fields = field_schema(spec.model)
        for entry in fields:
            if entry["name"] in spec.json_shapes:
                entry["json_shape"] = spec.json_shapes[entry["name"]]
            if spec.readonly:
                entry["readonly"] = True
        models_[spec.label] = {
            "collection": None,
            "verbose_name": spec.verbose,
            "fields": fields,
            "record": {
                "name": spec.name,
                "section": spec.section,
                "title_field": spec.title_field,
                "search_fields": list(spec.search_fields),
                "parent": spec.parent,
                "children": list(spec.children),
                "orderable": spec.orderable,
                "publishable": spec.publishable,
                "readonly": spec.readonly,
                "page_prefix": spec.page_prefix,
            },
        }
    digest = hashlib.sha1(json.dumps(models_, sort_keys=True).encode()).hexdigest()[:12]
    return {"version": digest, "models": models_}


class SchemaView(StudioView):
    """Per-model field descriptions, so the inspector renders a correct form for a block
    type nobody wrote a form for. A new block on the backend is editable immediately."""

    def get(self, request):
        return Response(build_schema())


#: The chrome models with structure of their own. Copy, media and SEO are chrome too,
#: but each already has a dedicated path; these six are what the chrome editor lists.
CHROME_STRUCTURAL = [
    "cms.navgroup",
    "cms.navitem",
    "cms.footercolumn",
    "cms.footerlink",
    "cms.sociallink",
    "cms.sitesettings",
]


class ChromeView(StudioView):
    """Current site-wide rows (nav menus, footer, social links, settings) with their ids.

    The public nav/footer endpoints deliberately omit primary keys, and an editor cannot
    PATCH what it cannot address — so the studio reads the same rows here. Values are
    the *live* rows on purpose: the pending map lets the UI badge staged edits, and the
    queue page is where a draft's contents are reviewed.
    """

    def get(self, request):
        rows = {}
        for label in CHROME_STRUCTURAL:
            model = engine.resolve_model(label)
            instances = [model.get_solo()] if label == "cms.sitesettings" else model.objects.all()
            rows[label] = [{"id": obj.pk, **snapshot(obj)} for obj in instances]
        pending = {
            f"{draft.model_label}:{draft.canvas_id}": draft.op
            # Chrome rows are site-wide, which the draft engine records as scope "".
            for draft in ContentDraft.objects.filter(scope="")
        }
        return Response({"rows": rows, "pending": pending})


# ------------------------------------------------------------------------------ edits


class CopyView(StudioView):
    """Upsert one copy row by its natural key.

    Copy is addressed by `(scope, key)` rather than by id because the row for a string
    the design shows may simply not exist yet — the site renders `""` for a missing key,
    and the editor should be able to fill it in without first creating anything.
    """

    def put(self, request, scope=None, key=None):
        if not is_valid_scope(scope):
            return Response({"detail": "Unknown page."}, status=status.HTTP_404_NOT_FOUND)
        payload = {
            "scope": scope,
            "key": key,
            "text": request.data.get("text", ""),
            "href": request.data.get("href", ""),
        }
        existing = CopyBlock.objects.filter(scope=scope, key=key).first()
        if existing is None:
            return self.write(
                model_label="cms.copyblock", op=ContentDraft.Op.CREATE, payload=payload
            )
        return self.write(
            model_label="cms.copyblock",
            op=ContentDraft.Op.UPDATE,
            object_id=existing.pk,
            payload={"text": payload["text"], "href": payload["href"]},
        )


class RowCreateView(StudioView):
    """Create any editable row — a new FAQ, stat, case card, nav item."""

    def post(self, request, model_label=None):
        engine.resolve_model(model_label)
        return self.write(model_label=model_label, op=ContentDraft.Op.CREATE, payload=self.body())


class RowDetailView(StudioView):
    def patch(self, request, model_label=None, pk=None):
        engine.resolve_model(model_label)
        return self.write(
            model_label=model_label,
            op=ContentDraft.Op.UPDATE,
            object_id=int(pk),
            payload=self.body(),
        )

    def delete(self, request, model_label=None, pk=None):
        engine.resolve_model(model_label)
        return self.write(model_label=model_label, op=ContentDraft.Op.DELETE, object_id=int(pk))


class ReorderView(StudioView):
    """Drag-to-reorder a block list.

    Expressed as ordinary per-row `sort_order` edits rather than a bulk `.update()`:
    a queryset update fires no `post_save`, so the content version would not bump and
    the site would keep serving the old order until some unrelated write moved it.
    """

    def post(self, request, model_label=None):
        engine.resolve_model(model_label)
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            return Response(
                {"detail": "ids must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST
            )
        items = [
            {"model_label": model_label, "object_id": int(row_id), "payload": {"sort_order": index}}
            for index, row_id in enumerate(ids)
        ]
        if self.mode == LIVE:
            revision = engine.apply_now_many(items, user=request.user, summary="Reorder")
            self.announce(
                scope=revision.scope if revision else "",
                model=model_label,
                object_id=None,
                op="reorder",
            )
        else:
            for item in items:
                self.write(op=ContentDraft.Op.UPDATE, **item)
        return Response({"mode": self.mode, "ordered": len(ids)})


class SeoView(StudioView):
    def put(self, request, page_key=None):
        if not is_valid_scope(page_key):
            return Response({"detail": "Unknown page."}, status=status.HTTP_404_NOT_FOUND)
        fields = {
            name: request.data[name]
            for name in ("title", "description", "canonical", "og_image")
            if name in request.data
        }
        existing = PageSEO.objects.filter(page_key=page_key).first()
        if existing is None:
            return self.write(
                model_label="cms.pageseo",
                op=ContentDraft.Op.CREATE,
                payload={"page_key": page_key, **fields},
            )
        return self.write(
            model_label="cms.pageseo",
            op=ContentDraft.Op.UPDATE,
            object_id=existing.pk,
            payload=fields,
        )


# ------------------------------------------------------------------------------ media


def _serialise_asset(request, asset: MediaAsset) -> dict:
    return {
        "id": asset.pk,
        "slot_key": asset.slot_key,
        "image": request.build_absolute_uri(asset.image.url) if asset.image else None,
        # The storage name is what a row edit writes; the URL is only for showing it.
        "name": asset.image.name if asset.image else "",
        "alt_text": asset.alt_text,
        "notes": asset.notes,
        "credit": asset.credit,
        "focal_x": asset.focal_x,
        "focal_y": asset.focal_y,
        "updated_at": asset.updated_at,
    }


def _store_upload(field, instance, upload):
    """Normalise and store one uploaded image for `field`, returning the storage name.

    Writing to storage directly bypasses `ProcessedImageField.pre_save`, so the resize,
    EXIF strip and re-encode are applied by hand — an image uploaded from the Studio must
    be byte-for-byte what the admin would have stored.
    """
    validate_upload(upload)
    if isinstance(field, ProcessedImageField):
        upload = process_image(upload, max_edge=field.max_edge, to_format=field.to_format)
    return field.storage.save(field.generate_filename(instance, upload.name), upload)


#: The upload views also accept a ticket, so the browser can send a photograph straight
#: to Django instead of through the studio's 4.5 MB proxy.
UPLOAD_AUTH = [StudioTokenAuthentication, StudioUploadTicketAuthentication]


class MediaView(StudioView):
    """The media library, and the upload that fills a slot.

    Unlike the admin's `MediaUploadView`, this creates the slot when it is missing —
    the canvas can hand back a slot key the inventory has not caught up with yet. The
    key is still validated, so it cannot escape the `<scope>:<slot>` namespace.
    """

    authentication_classes = UPLOAD_AUTH

    def get(self, request):
        # Ordered, or the page boundary lands wherever the planner feels like — the same
        # bug the public media endpoint had, where *which* rows survived the cap was
        # whatever the table scan returned first.
        queryset = MediaAsset.objects.order_by("slot_key")
        if scope := request.query_params.get("scope"):
            queryset = queryset.filter(slot_key__startswith=f"{scope}:")
        if term := request.query_params.get("q"):
            queryset = queryset.filter(
                models.Q(slot_key__icontains=term)
                | models.Q(notes__icontains=term)
                | models.Q(alt_text__icontains=term)
            )
        state = request.query_params.get("state")
        if state == "filled":
            queryset = queryset.exclude(image="")
        elif state == "empty":
            queryset = queryset.filter(image="")
        page, size = self.page_number(default_size=60, max_size=200)
        total = queryset.count()
        assets = list(queryset[(page - 1) * size : page * size])
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": size,
                "pages": max(1, -(-total // size)),
                "slots": [_serialise_asset(request, asset) for asset in assets],
            }
        )

    def post(self, request):
        slot_key = (request.data.get("slot_key") or "").strip()
        upload = request.FILES.get("image")
        if not upload:
            return Response(
                {"detail": "An image file is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            validate_slot_key(slot_key)
        except Exception as exc:  # ValidationError — the message is the useful part
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # An empty slot row renders nothing (`compose_page` skips assets with no image),
        # so creating it here is the same no-op `sync_media_slots` performs — it gives
        # the draft a stable id to hang the new image off.
        asset, _created = MediaAsset.objects.get_or_create(slot_key=slot_key)

        # The file lands in storage now regardless of mode; the draft only decides when
        # the *slot* starts pointing at it. `save=False` keeps the live row untouched.
        # An unpublished upload leaves an orphaned file, which is cheap — a published
        # slot pointing at a file nobody wrote would be a broken image on the live site.
        field = MediaAsset._meta.get_field("image")
        name = _store_upload(field, asset, upload)

        # A new photograph is the agency's own unless told otherwise; the stock credit
        # from the seeded placeholder must not survive its replacement.
        payload = {"image": name, "credit": request.data.get("credit", "")}
        if "alt_text" in request.data:
            payload["alt_text"] = request.data["alt_text"]
        response = self.write(
            model_label="cms.mediaasset",
            op=ContentDraft.Op.UPDATE,
            object_id=asset.pk,
            payload=payload,
        )
        response.data["slot_key"] = slot_key
        response.data["name"] = name
        response.data["image"] = request.build_absolute_uri(field.storage.url(name))
        return response


class MediaSlotView(StudioView):
    """Edit one slot by key — alt text, focal point, credit, and the image itself, whether
    that is a fresh file, a storage name reused from another slot, or "" to clear it.

    Addressed by slot key rather than row id because the row may not exist yet: the
    payload only carries filled slots, and the editor's first act on an empty one is often
    to write its alt text or point it at a photo already in the library.
    """

    authentication_classes = UPLOAD_AUTH

    def put(self, request, slot_key=None):
        return self.patch(request, slot_key=slot_key)

    def patch(self, request, slot_key=None):
        try:
            validate_slot_key(slot_key)
        except Exception as exc:  # ValidationError
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        asset, _created = MediaAsset.objects.get_or_create(slot_key=slot_key)
        field = MediaAsset._meta.get_field("image")

        payload = {}
        upload = request.FILES.get("image")
        if upload:
            payload["image"] = _store_upload(field, asset, upload)
            payload["credit"] = request.data.get("credit", "")
        elif "image" in request.data:
            name = (request.data.get("image") or "").strip()
            if name and not field.storage.exists(name):
                return Response(
                    {"detail": "That image is not in the library."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            payload["image"] = name
            if "credit" not in request.data:
                # Reusing a library image inherits its credit; clearing clears it.
                source = MediaAsset.objects.filter(image=name).exclude(pk=asset.pk).first()
                payload["credit"] = source.credit if (name and source) else ""
        for key in ("alt_text", "credit", "notes"):
            if key in request.data:
                payload[key] = request.data[key]
        for key in ("focal_x", "focal_y"):
            if key in request.data:
                try:
                    payload[key] = min(1.0, max(0.0, float(request.data[key])))
                except (TypeError, ValueError):
                    return Response(
                        {"detail": f"{key} must be a number between 0 and 1."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        if not payload:
            return Response({"detail": "Nothing to change."}, status=status.HTTP_400_BAD_REQUEST)

        response = self.write(
            model_label="cms.mediaasset",
            op=ContentDraft.Op.UPDATE,
            object_id=asset.pk,
            payload=payload,
        )
        response.data["slot_key"] = slot_key
        name = payload.get("image", asset.image.name if asset.image else "")
        response.data["name"] = name
        response.data["image"] = (
            request.build_absolute_uri(field.storage.url(name)) if name else None
        )
        return response


class UploadView(StudioView):
    """Upload a file for an image field that belongs to a row rather than to a named slot.

    A step illustration, a testimonial portrait and a case-card photo are columns on the
    block row itself, not `MediaAsset` slots — so they cannot go through the media
    library. This stores the file and hands back the storage name; the caller then writes
    that name onto the field like any other value, which keeps the upload and the edit on
    the same draft/live rails as everything else.
    """

    authentication_classes = UPLOAD_AUTH

    def post(self, request):
        model_label = (request.data.get("model_label") or "").lower()
        field_name = request.data.get("field") or ""
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "A file is required."}, status=status.HTTP_400_BAD_REQUEST)

        model = engine.resolve_upload_model(model_label)
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return Response(
                {"detail": f"{model_label} has no field {field_name}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(field, models.FileField):
            return Response(
                {"detail": f"{field_name} does not hold a file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # `generate_filename` needs an instance for `upload_to` callables; a bare one is
        # enough because every `upload_to` in the CMS is a static path.
        name = _store_upload(field, model(), upload)
        return Response({"name": name, "url": request.build_absolute_uri(field.storage.url(name))})


class MediaSyncView(StudioView):
    """Re-derive the slot inventory from the content that exists (new city, new project
    type, new gallery card). Wraps `apps.cms.slots.sync_media_slots`."""

    def post(self, request):
        created, pruned = sync_media_slots()
        return Response({"created": created, "pruned": pruned})


# ---------------------------------------------------------------------------- publish


class QueueView(StudioView):
    def get(self, request):
        page, size = self.page_number(default_size=100, max_size=500)
        queryset = ContentDraft.objects.select_related("created_by").order_by(
            "scope", "-updated_at"
        )
        total = queryset.count()
        rows = []
        for draft in queryset[(page - 1) * size : page * size]:
            rows.append(
                {
                    "id": draft.pk,
                    "scope": draft.scope,
                    "model_label": draft.model_label,
                    "object_id": draft.canvas_id,
                    "op": draft.op,
                    "payload": draft.payload,
                    "by": draft.created_by.display_name if draft.created_by else "",
                    "at": draft.updated_at,
                }
            )
        by_scope = {}
        for row in rows:
            by_scope.setdefault(row["scope"], []).append(row)
        return Response(
            {
                "total": total,
                "page": page,
                "page_size": size,
                "scopes": [
                    {"scope": scope, "route": route_for(scope), "changes": changes}
                    for scope, changes in by_scope.items()
                ],
            }
        )


def _selected_drafts(request):
    """The drafts a publish/discard call targets: a page, a set of ids, one record (with
    its children), or everything."""
    queryset = ContentDraft.objects.all()
    if scope := request.data.get("scope"):
        queryset = queryset.filter(scope=scope)
    if ids := request.data.get("ids"):
        queryset = queryset.filter(pk__in=ids)
    label = (request.data.get("model_label") or "").lower()
    object_id = request.data.get("object_id")
    if label and object_id is not None:
        object_id = int(object_id)
        selection = models.Q(model_label=label, object_id=object_id)
        if object_id < 0:
            selection = models.Q(model_label=label, pk=-object_id, op=ContentDraft.Op.CREATE)
        spec = BY_LABEL.get(label)
        for child_label in spec.children if spec else ():
            child = BY_LABEL[child_label]
            live_ids = child.model._default_manager.filter(**{child.parent: object_id}).values_list(
                "pk", flat=True
            )
            selection |= models.Q(model_label=child_label, object_id__in=list(live_ids))
            selection |= models.Q(
                model_label=child_label,
                op=ContentDraft.Op.CREATE,
                **{f"payload__{child.parent}": object_id},
            )
        queryset = queryset.filter(selection)
    return queryset


class PublishView(StudioView):
    """Apply the selected drafts, purge the live site *now*, and say how it went.

    The purge is synchronous on purpose (bounded by the ping's own 3 s timeout): the
    editor who pressed Publish is waiting to be told the site has it. The debounced,
    signal-driven ping still runs for everything else. After responding, the published
    routes are re-fetched in the background so the next visitor gets a warm page and the
    editors get a `site.warmed` event.
    """

    def post(self, request):
        selected = list(_selected_drafts(request))
        scopes = sorted({draft.scope for draft in selected})
        revision = engine.publish(selected, user=request.user, scope=request.data.get("scope", ""))
        if revision is None:
            return Response({"published": 0, "revision": None, "purge": None})
        purge = ping_now(getattr(revision, "purge_tags", set()))
        routes = [route_for(scope) for scope in scopes]
        schedule_warm(routes)
        emit(
            {
                "type": "published",
                "scopes": scopes,
                "revision": revision.pk,
                "summary": revision.summary,
                "purge": purge,
                **actor(request),
            }
        )
        return Response(
            {
                "published": len(selected),
                "revision": revision.pk,
                "summary": revision.summary,
                "purge": purge,
                "scopes": scopes,
            }
        )


class DiscardView(StudioView):
    def post(self, request):
        selected = list(_selected_drafts(request))
        scopes = sorted({draft.scope for draft in selected})
        discarded = engine.discard(selected)
        if discarded:
            emit({"type": "discarded", "scopes": scopes, "count": discarded, **actor(request)})
        return Response({"discarded": discarded})


class RevisionListView(StudioView):
    def get(self, request):
        queryset = ContentRevision.objects.select_related("applied_by")
        if scope := request.query_params.get("scope"):
            queryset = queryset.filter(scope=scope)
        page, size = self.page_number(default_size=50, max_size=200)
        total = queryset.count()
        return Response(
            {
                "count": total,
                "page": page,
                "page_size": size,
                "revisions": [
                    {
                        "id": revision.pk,
                        "scope": revision.scope,
                        "summary": revision.summary,
                        "by": revision.applied_by.display_name if revision.applied_by else "",
                        "at": revision.created_at,
                        "reverted_at": revision.reverted_at,
                        "rows": len(revision.changes),
                    }
                    for revision in queryset[(page - 1) * size : page * size]
                ],
            }
        )


class RevisionRevertView(StudioView):
    def post(self, request, pk=None):
        revision = ContentRevision.objects.filter(pk=pk).first()
        if revision is None:
            return Response({"detail": "Unknown revision."}, status=status.HTTP_404_NOT_FOUND)
        if revision.reverted_at is not None:
            return Response({"detail": "Already reverted."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            undo = engine.revert(revision, user=request.user)
        return Response({"revision": undo.pk, "summary": undo.summary})
