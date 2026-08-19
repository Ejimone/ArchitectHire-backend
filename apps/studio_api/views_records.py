"""The generic records API: every collection in `registry.py`, read the Studio's way.

Reads only. Writes go through the same `rows/<label>/` endpoints the blocks use, so a
case study, a job posting or a city's permit prose is staged, previewed, published and
reverted by exactly the machinery the page canvas already trusts.

Two shapes:

* `edit`   — the row as a form sees it: every editable field by name, files as storage
             names (plus URLs for thumbnails), the draft overlaid, pending rows included.
* `public` — the row as the site sees it: the model's public serializer run over the
             draft-overlaid instance, with `id` added. This is what a wrapped Studio page
             renders in draft mode, so a staged gallery image is visible on the canvas
             before it is published.
"""

from django.db import models
from rest_framework import status
from rest_framework.response import Response

from . import drafts as engine
from .fields import editable_fields, field_schema, snapshot
from .models import ContentDraft
from .registry import BY_LABEL, SPECS, CollectionSpec, spec_for
from .views import DRAFT, StudioView


def _resolve(label_or_name: str) -> CollectionSpec:
    spec = spec_for(label_or_name)
    if spec is None:
        raise engine.DraftError(f"{label_or_name} is not a collection the Studio knows.")
    return spec


def spec_summary(spec: CollectionSpec) -> dict:
    return {
        "label": spec.label,
        "name": spec.name,
        "section": spec.section,
        "verbose": spec.verbose,
        "title_field": spec.title_field,
        "search_fields": list(spec.search_fields),
        "parent": spec.parent,
        "children": list(spec.children),
        "orderable": spec.orderable,
        "publishable": spec.publishable,
        "readonly": spec.readonly,
        "json_shapes": spec.json_shapes,
        "page_prefix": spec.page_prefix,
    }


def _drafts_for(spec: CollectionSpec):
    return list(ContentDraft.objects.filter(model_label=spec.label))


def _file_urls(request, obj) -> dict:
    urls = {}
    for field_ in editable_fields(obj):
        if isinstance(field_, models.FileField):
            value = getattr(obj, field_.name)
            urls[field_.name] = request.build_absolute_uri(value.url) if value else None
    return urls


def _title(spec: CollectionSpec, data: dict) -> str:
    return (
        str(data.get(spec.title_field) or "")
        or f"{spec.verbose[:-1] if spec.verbose.endswith('s') else spec.verbose} #{data.get('id')}"
    )


def edit_row(request, spec: CollectionSpec, obj, pending: str | None = None) -> dict:
    data = snapshot(obj)
    row = {
        "id": obj.pk,
        **data,
        "pending": pending,
        "files": _file_urls(request, obj),
        "route": spec.route(obj) if obj.pk and obj.pk > 0 else None,
        "page_key": spec.page_key(obj),
    }
    row["title"] = _title(spec, row)
    return row


def overlaid_rows(request, spec: CollectionSpec, queryset, mode: str, parent_id=None):
    """`(instances, pending_by_id)` for `queryset` with this label's drafts folded in.

    Live mode returns the rows as they are. Draft mode applies pending updates, drops
    pending deletes and appends pending creates (negative ids), optionally only those
    whose payload names `parent_id`.
    """
    instances = list(queryset)
    if mode != DRAFT:
        return instances, {}

    drafts = _drafts_for(spec)
    by_object = {d.object_id: d for d in drafts if d.object_id is not None}
    pending = {}
    result = []
    for obj in instances:
        draft = by_object.get(obj.pk)
        if draft is None:
            result.append(obj)
            continue
        pending[obj.pk] = draft.op
        if draft.op == ContentDraft.Op.DELETE:
            continue
        result.append(engine._row_for(spec.model, draft, obj))
    for draft in drafts:
        if draft.op != ContentDraft.Op.CREATE:
            continue
        if parent_id is not None and str(draft.payload.get(spec.parent)) != str(parent_id):
            continue
        obj = engine._row_for(spec.model, draft, None)
        pending[obj.pk] = draft.op
        result.append(obj)
    return result, pending


def attach_children(request, spec: CollectionSpec, obj, mode: str) -> dict:
    """Overlay each child collection onto `obj` so nested serializers see the drafts, and
    return the children as edit rows keyed by label."""
    children = {}
    for child_label in spec.children:
        child_spec = BY_LABEL[child_label]
        parent_field = child_spec.model._meta.get_field(child_spec.parent)
        queryset = child_spec.model._default_manager.filter(**{child_spec.parent: obj.pk}).order_by(
            *child_spec.ordering
        )
        rows, pending = overlaid_rows(request, child_spec, queryset, mode, parent_id=obj.pk)
        # A QuerySet whose result cache is the overlaid list, parked where Django's
        # prefetch machinery would put it: `obj.<related_name>.all()` now yields the
        # drafts without a query, and the nested serializer never knows the difference.
        cache_name = parent_field.remote_field.cache_name
        cached = child_spec.model._default_manager.none()
        cached._result_cache = rows
        cached._prefetch_done = True
        obj._prefetched_objects_cache = {
            **getattr(obj, "_prefetched_objects_cache", {}),
            cache_name: cached,
        }
        children[child_label] = [
            edit_row(request, child_spec, child, pending.get(child.pk)) for child in rows
        ]
    return children


def public_row(request, spec: CollectionSpec, obj, mode: str) -> dict:
    if spec.children:
        attach_children(request, spec, obj, mode)
    if spec.serializer is None:
        data = snapshot(obj)
    else:
        data = dict(spec.serializer(obj, context={"request": request}).data)
    data["id"] = obj.pk
    # Nested children (a case study's gallery, a category's services, a policy's
    # sections) come out of the site's serializers without ids. The canvas needs them to
    # make each child clickable, so they are injected by position — the nested list is
    # rendered from the same overlaid rows, in the same order.
    for child_label in spec.children:
        child_spec = BY_LABEL[child_label]
        parent_field = child_spec.model._meta.get_field(child_spec.parent)
        accessor = parent_field.remote_field.get_accessor_name()
        rows = getattr(obj, "_prefetched_objects_cache", {}).get(
            parent_field.remote_field.cache_name
        )
        nested = data.get(accessor)
        if rows is None or not isinstance(nested, list) or len(nested) != len(rows):
            continue
        for entry, child in zip(nested, rows, strict=True):
            if isinstance(entry, dict):
                entry["id"] = child.pk
    return data


def _search(queryset, spec: CollectionSpec, term: str):
    if not term or not spec.search_fields:
        return queryset
    condition = models.Q()
    for name in spec.search_fields:
        condition |= models.Q(**{f"{name}__icontains": term})
    return queryset.filter(condition)


def _ordering(spec: CollectionSpec, requested: str) -> tuple[str, ...]:
    if requested:
        name = requested.lstrip("-")
        if name in {f.name for f in spec.model._meta.fields}:
            return (requested,)
    return spec.ordering


class RecordsIndexView(StudioView):
    """Every collection, grouped by section, with row and pending counts."""

    def get(self, request):
        pending = {
            row["model_label"]: row["n"]
            for row in ContentDraft.objects.values("model_label").annotate(n=models.Count("id"))
        }
        sections = {}
        for spec in SPECS:
            sections.setdefault(spec.section, []).append(
                {
                    **spec_summary(spec),
                    "count": spec.model._default_manager.count(),
                    "pending": pending.get(spec.label, 0),
                }
            )
        return Response(
            {
                "sections": [
                    {"section": name, "collections": rows} for name, rows in sections.items()
                ]
            }
        )


class RecordListView(StudioView):
    def get(self, request, label=None):
        spec = _resolve(label)
        shape = request.query_params.get("shape", "edit")
        queryset = spec.model._default_manager.all()
        parent_id = request.query_params.get("parent")
        if parent_id and spec.parent:
            queryset = queryset.filter(**{spec.parent: parent_id})
        queryset = _search(queryset, spec, request.query_params.get("q", "").strip())
        queryset = queryset.order_by(*_ordering(spec, request.query_params.get("ordering", "")))
        page, size = self.page_number(default_size=50, max_size=500)
        total = queryset.count()
        window = queryset[(page - 1) * size : page * size]
        rows, pending = overlaid_rows(request, spec, window, self.mode, parent_id=parent_id)
        if shape == "public":
            results = [public_row(request, spec, obj, self.mode) for obj in rows]
        else:
            results = [edit_row(request, spec, obj, pending.get(obj.pk)) for obj in rows]
        return Response(
            {
                "collection": spec_summary(spec),
                "count": total,
                "page": page,
                "page_size": size,
                "results": results,
            }
        )


class RecordDetailView(StudioView):
    def get(self, request, label=None, pk=None):
        spec = _resolve(label)
        pk = int(pk)
        pending_op = None
        if pk < 0:
            draft = engine.draft_for_canvas_id(spec.label, pk)
            if draft is None:
                return Response({"detail": "No such record."}, status=status.HTTP_404_NOT_FOUND)
            obj = engine._row_for(spec.model, draft, None)
            pending_op = draft.op
        else:
            obj = spec.model._default_manager.filter(pk=pk).first()
            if obj is None:
                return Response({"detail": "No such record."}, status=status.HTTP_404_NOT_FOUND)
            if self.mode == DRAFT:
                draft = ContentDraft.objects.filter(model_label=spec.label, object_id=pk).first()
                if draft is not None:
                    pending_op = draft.op
                    if draft.op != ContentDraft.Op.DELETE:
                        obj = engine._row_for(spec.model, draft, obj)

        children = attach_children(request, spec, obj, self.mode) if spec.children else {}
        record = edit_row(request, spec, obj, pending_op)
        public = public_row(request, spec, obj, self.mode) if spec.serializer else None

        choices = {}
        for field_ in editable_fields(spec.model):
            if field_.is_relation:
                related = field_.related_model._default_manager.all()[:500]
                choices[field_.name] = [{"id": row.pk, "label": str(row)} for row in related]

        return Response(
            {
                "collection": spec_summary(spec),
                "record": record,
                "public": public,
                "children": children,
                "choices": choices,
                "schema": field_schema(spec.model),
            }
        )
