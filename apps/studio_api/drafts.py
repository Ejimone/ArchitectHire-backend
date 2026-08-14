"""Staging, previewing, publishing and reverting content edits.

The rule the whole module is built around: **a draft is previewed by building the real
row and running the real serializer over it.** Never by patching the composed JSON with
raw field values. `Persona.points` is a newline-delimited TextField that the site reads
as `points_list`; `Step.image` is a storage path the site reads as a URL. Anything that
short-cuts the serializer previews a page the site would not render.
"""

from django.apps import apps as django_apps
from django.db import models, transaction
from django.utils import timezone

from apps.cms.compose import BLOCK_KEY_BY_LABEL, BLOCK_MODELS, BLOCK_SERIALIZERS
from apps.cms.serializers import MediaAssetSerializer, PageSEOSerializer

from .fields import assign, snapshot
from .models import ContentDraft, ContentRevision

# Site-chrome and page-furniture models the Studio may edit alongside the 14 block
# types. An allowlist rather than "any model": `model_label` arrives from the client.
CHROME_MODELS = [
    "cms.copyblock",
    "cms.mediaasset",
    "cms.pageseo",
    "cms.navgroup",
    "cms.navitem",
    "cms.footercolumn",
    "cms.footerlink",
    "cms.sociallink",
    "cms.sitesettings",
]

EDITABLE_LABELS = frozenset(list(BLOCK_MODELS) + CHROME_MODELS)


class DraftError(Exception):
    """A staged edit that cannot be applied — surfaced to the client as a 400."""


def resolve_model(model_label: str):
    label = (model_label or "").lower()
    if label not in EDITABLE_LABELS:
        raise DraftError(f"{model_label} is not editable from the Studio.")
    return django_apps.get_model(label)


def media_scope(slot_key: str) -> str:
    """`<scope>:<slot>`, where the scope may itself contain a colon (`city:oakland:hero`),
    so split from the right — the same rule `validate_slot_key` applies."""
    return slot_key.rpartition(":")[0]


def scope_for(model_label: str, data: dict, obj=None) -> str:
    """Which page a row shows up on. Blank means site-wide (nav, footer, settings)."""

    def value(name):
        if name in data:
            return data[name]
        return getattr(obj, name, "") if obj is not None else ""

    if model_label in BLOCK_MODELS or model_label == "cms.copyblock":
        return value("scope") or ""
    if model_label == "cms.pageseo":
        return value("page_key") or ""
    if model_label == "cms.mediaasset":
        return media_scope(value("slot_key") or "")
    return ""


# --------------------------------------------------------------------------- staging


def stage(*, model_label: str, op: str, object_id=None, payload=None, user=None) -> ContentDraft:
    """Queue an edit. Re-staging an already-staged row merges into the existing draft
    rather than queueing a second one, so the queue always reads as a list of rows
    rather than a list of keystrokes."""
    model = resolve_model(model_label)
    payload = payload or {}

    if op == ContentDraft.Op.CREATE:
        scope = scope_for(model_label, payload)
        draft = ContentDraft(
            model_label=model_label,
            op=op,
            payload={**_append_position(model, scope, payload), **payload},
            scope=scope,
            created_by=user,
        )
        draft.save()
        return draft

    obj = model._default_manager.filter(pk=object_id).first()
    if obj is None:
        raise DraftError(f"{model_label}:{object_id} does not exist.")

    existing = ContentDraft.objects.filter(model_label=model_label, object_id=object_id).first()
    if existing is None:
        existing = ContentDraft(model_label=model_label, object_id=object_id, created_by=user)

    if op == ContentDraft.Op.DELETE:
        # A delete supersedes whatever was pending: the row is going away regardless.
        existing.op = op
        existing.payload = {}
    elif existing.op == ContentDraft.Op.DELETE:
        return existing  # already staged for removal; an edit to it is meaningless
    else:
        existing.op = op
        existing.payload = {**existing.payload, **payload}
    existing.scope = scope_for(model_label, existing.payload, obj)
    existing.save()
    return existing


def _append_position(model, scope: str, payload: dict) -> dict:
    """Where a newly added row goes: the end of its list.

    "Add a stat" means "add another one after the ones I have", but `sort_order` defaults
    to 0, which would drop the new row into the middle of a hand-ordered list. Only the
    rows sharing this row's `group` count — one page renders several lists from the same
    model, told apart by that field.
    """
    # Scoped blocks only. `NavItem` and `FooterLink` are orderable too, but they are
    # ordered within a parent group rather than within a page scope, and the studio does
    # not create them yet.
    if model._meta.label_lower not in BLOCK_MODELS or "sort_order" in payload:
        return {}
    siblings = model._default_manager.filter(scope=scope, group=payload.get("group", ""))
    last = siblings.aggregate(models.Max("sort_order"))["sort_order__max"]
    # Pending creates have no row yet, so count them too — adding three in a row should
    # produce three positions, not three rows fighting over one.
    staged = ContentDraft.objects.filter(
        model_label=model._meta.label_lower, op=ContentDraft.Op.CREATE, scope=scope
    ).count()
    return {"sort_order": (last or 0) + 1 + staged}


def stage_create_edit(draft: ContentDraft, payload: dict) -> ContentDraft:
    """Edit a row that is itself still pending — the canvas addresses it by `-draft.pk`."""
    draft.payload = {**draft.payload, **payload}
    draft.scope = scope_for(draft.model_label, draft.payload)
    draft.save()
    return draft


def draft_for_canvas_id(model_label: str, canvas_id: int) -> ContentDraft | None:
    """Resolve the negative id the canvas uses for a pending create."""
    if canvas_id >= 0:
        return None
    return ContentDraft.objects.filter(
        pk=-canvas_id, model_label=model_label, op=ContentDraft.Op.CREATE
    ).first()


# --------------------------------------------------------------------------- preview


def _live_row(model, draft):
    """The row a draft targets, or None for a create (and for an update whose row has
    since been deleted elsewhere)."""
    if draft.object_id is None:
        return None
    return model._default_manager.filter(pk=draft.object_id).first()


def _row_for(model, draft, base=None):
    """The model instance a draft describes, unsaved. `base` is the live row for an
    update; None for a create."""
    obj = base if base is not None else model()
    assign(obj, draft.payload)
    if base is None:
        # Negative pk so the canvas can address a row that has no database identity yet.
        obj.pk = -draft.pk
    return obj


def _sort_key(value):
    return value if value is not None else 0


def overlay(payload: dict, page_key: str, request) -> dict:
    """Fold every pending draft for `page_key` into a composed page payload.

    Returns the same payload object, plus a `pending` map naming the rows that carry
    unpublished edits so the canvas can badge them.
    """
    drafts = list(ContentDraft.objects.filter(scope=page_key))
    pending = {}
    touched_collections = {}

    for draft in drafts:
        model = resolve_model(draft.model_label)
        label = draft.model_label
        pending[f"{label}:{draft.canvas_id}"] = draft.op

        if label in BLOCK_MODELS:
            key = BLOCK_KEY_BY_LABEL[label]
            rows = payload["blocks"].setdefault(key, [])
            touched_collections.setdefault(key, (model, {}))
            _, orders = touched_collections[key]

            if draft.op == ContentDraft.Op.DELETE:
                payload["blocks"][key] = [r for r in rows if r["id"] != draft.object_id]
                continue

            base = _live_row(model, draft)
            if draft.op == ContentDraft.Op.UPDATE and base is None:
                continue  # row vanished under us; the draft is stale
            obj = _row_for(model, draft, base)
            data = BLOCK_SERIALIZERS[label](obj, context={"request": request}).data
            orders[data["id"]] = _sort_key(obj.sort_order)
            replaced = [data if r["id"] == data["id"] else r for r in rows]
            payload["blocks"][key] = (
                replaced if any(r["id"] == data["id"] for r in rows) else [*rows, data]
            )

        elif label == "cms.copyblock":
            base = _live_row(model, draft)
            if draft.op == ContentDraft.Op.DELETE:
                if base is not None:
                    payload["copy"].pop(base.key, None)
                continue
            obj = _row_for(model, draft, base)
            payload["copy"][obj.key] = {"text": obj.text, "href": obj.href}

        elif label == "cms.mediaasset":
            base = _live_row(model, draft)
            if draft.op == ContentDraft.Op.DELETE:
                if base is not None:
                    payload["media"].pop(base.slot_key, None)
                continue
            obj = _row_for(model, draft, base)
            data = MediaAssetSerializer(obj, context={"request": request}).data
            # `compose_page` omits empty slots, so a draft that fills one has to add it
            # and a draft that clears one has to take it back out.
            if obj.image:
                payload["media"][obj.slot_key] = data
            else:
                payload["media"].pop(obj.slot_key, None)

        elif label == "cms.pageseo":
            obj = _row_for(model, draft, _live_row(model, draft))
            payload["seo"] = PageSEOSerializer(obj, context={"request": request}).data

    _resort(payload, touched_collections)
    payload["pending"] = pending
    return payload


def _resort(payload, touched_collections):
    """Re-apply `["sort_order", "id"]` ordering to any collection a draft disturbed.

    `compose_page` ordered the live rows already; a draft that changes `sort_order`, or
    appends a pending create, invalidates that for its collection only.
    """
    for key, (model, draft_orders) in touched_collections.items():
        rows = payload["blocks"].get(key)
        if not rows:
            continue
        live = dict(
            model._default_manager.filter(pk__in=[r["id"] for r in rows]).values_list(
                "id", "sort_order"
            )
        )
        orders = {**live, **draft_orders}
        rows.sort(key=lambda row: (orders.get(row["id"], 0), abs(row["id"])))


# --------------------------------------------------------------------------- publish


def _apply(draft, changes):
    """Apply one draft to the live table, recording a before/after pair."""
    model = resolve_model(draft.model_label)

    if draft.op == ContentDraft.Op.CREATE:
        obj = model()
        assign(obj, draft.payload)
        obj.save()
        changes.append(
            {
                "model_label": draft.model_label,
                "object_id": obj.pk,
                "op": draft.op,
                "before": None,
                "after": snapshot(obj),
            }
        )
        return

    obj = model._default_manager.filter(pk=draft.object_id).first()
    if obj is None:
        return  # deleted elsewhere between staging and publishing; nothing to apply
    before = snapshot(obj)

    if draft.op == ContentDraft.Op.DELETE:
        obj.delete()  # per-row, so post_delete fires and the caches purge
        changes.append(
            {
                "model_label": draft.model_label,
                "object_id": draft.object_id,
                "op": draft.op,
                "before": before,
                "after": None,
            }
        )
        return

    assign(obj, draft.payload)
    obj.save()  # never .update(): post_save is what bumps the cache and pings the site
    changes.append(
        {
            "model_label": draft.model_label,
            "object_id": obj.pk,
            "op": draft.op,
            "before": before,
            "after": snapshot(obj),
        }
    )


# Creates first so a row exists for anything that references it, deletes last so a
# reorder staged alongside a delete still sees the row it is ordering against.
_ORDER = [ContentDraft.Op.CREATE, ContentDraft.Op.UPDATE, ContentDraft.Op.DELETE]


def publish(drafts, user=None, scope: str = "") -> ContentRevision | None:
    """Apply a set of drafts in one transaction and snapshot the result."""
    drafts = list(drafts)
    if not drafts:
        return None

    with transaction.atomic():
        changes = []
        for op in _ORDER:
            for draft in [d for d in drafts if d.op == op]:
                _apply(draft, changes)
        ContentDraft.objects.filter(pk__in=[d.pk for d in drafts]).delete()
        return ContentRevision.objects.create(
            scope=scope,
            summary=_summarise(changes),
            applied_by=user,
            changes=changes,
        )


def apply_now(*, model_label: str, op: str, object_id=None, payload=None, user=None):
    """Live mode: skip the queue and write straight to the site.

    Still goes through `_apply`, so a live edit is snapshotted into a revision exactly
    like a published one — "edit live" costs you the queue, not the undo history.
    """
    resolve_model(model_label)
    payload = payload or {}
    draft = ContentDraft(
        model_label=model_label,
        op=op,
        object_id=object_id,
        payload=payload,
        created_by=user,
    )
    with transaction.atomic():
        changes = []
        _apply(draft, changes)
        if not changes:
            raise DraftError(f"{model_label}:{object_id} does not exist.")
        scope = scope_for(model_label, changes[0]["after"] or changes[0]["before"] or {})
        revision = ContentRevision.objects.create(
            scope=scope,
            summary=f"Live edit — {_summarise(changes)}",
            applied_by=user,
            changes=changes,
        )
    return changes[0], revision


def apply_now_many(items, user=None, summary: str = "Live edit") -> ContentRevision | None:
    """Live mode for a batch — one transaction, one revision.

    A drag-to-reorder touches every row in a list; without this it would land in history
    as a dozen separate revisions and be miserable to roll back.
    """
    staged = [
        ContentDraft(
            model_label=item["model_label"],
            op=item.get("op", ContentDraft.Op.UPDATE),
            object_id=item.get("object_id"),
            payload=item.get("payload") or {},
            created_by=user,
        )
        for item in items
    ]
    for draft in staged:
        resolve_model(draft.model_label)
    with transaction.atomic():
        changes = []
        for draft in staged:
            _apply(draft, changes)
        if not changes:
            return None
        return ContentRevision.objects.create(
            scope=scope_for(staged[0].model_label, changes[0]["after"] or {}),
            summary=f"{summary} — {_summarise(changes)}",
            applied_by=user,
            changes=changes,
        )


def discard(drafts) -> int:
    """Throw staged edits away without touching the live site."""
    ids = [d.pk for d in drafts]
    ContentDraft.objects.filter(pk__in=ids).delete()
    return len(ids)


def _summarise(changes) -> str:
    if not changes:
        return "No changes"
    counts = {}
    for change in changes:
        counts[change["op"]] = counts.get(change["op"], 0) + 1
    return ", ".join(
        f"{count} {op}{'s' if count > 1 else ''}" for op, count in sorted(counts.items())
    )


def revert(revision: ContentRevision, user=None) -> ContentRevision:
    """Undo a published revision, recording the undo as a revision of its own so it can
    itself be undone."""
    with transaction.atomic():
        changes = []
        for change in reversed(revision.changes):
            model = resolve_model(change["model_label"])
            object_id = change["object_id"]

            if change["op"] == ContentDraft.Op.CREATE:
                obj = model._default_manager.filter(pk=object_id).first()
                if obj is not None:
                    obj.delete()
                    changes.append({**change, "op": ContentDraft.Op.DELETE, "after": None})
                continue

            if change["op"] == ContentDraft.Op.DELETE:
                obj = model()
                assign(obj, change["before"])
                # Restore the original pk: hrefs, media slot keys and the canvas all
                # address rows by id, so a re-created row with a new id is a broken link.
                obj.pk = object_id
                obj.save(force_insert=True)
                changes.append({**change, "op": ContentDraft.Op.CREATE, "before": None})
                continue

            obj = model._default_manager.filter(pk=object_id).first()
            if obj is None:
                continue
            assign(obj, change["before"])
            obj.save()
            changes.append({**change, "before": change["after"], "after": change["before"]})

        revision.reverted_at = timezone.now()
        revision.save(update_fields=["reverted_at", "updated_at"])
        return ContentRevision.objects.create(
            scope=revision.scope,
            summary=f"Reverted: {revision.summary}",
            applied_by=user,
            changes=changes,
        )
