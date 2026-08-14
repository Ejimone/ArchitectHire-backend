"""Turning model rows into JSON and back.

Three callers share this: draft payloads, revision snapshots, and the schema the Studio
inspector builds its form from. They have to agree — a field the inspector can edit but
the snapshot cannot store is a field that silently loses its value on rollback — so the
field list is derived once, here, from the model itself.
"""

from datetime import date
from decimal import Decimal

from django.db import models
from django.utils.dateparse import parse_date, parse_datetime

# Bookkeeping the Studio never edits directly, and `id` which is not a field value.
SKIPPED = {"id", "created_at", "updated_at"}

# Editable, but the Studio drives them through dedicated affordances (the page tree, the
# drag handle, the publish button) rather than a text input in the inspector.
SYSTEM = {"scope", "sort_order", "status", "published_at"}

_TYPES = [
    (models.ImageField, "image"),
    (models.FileField, "file"),
    (models.BooleanField, "boolean"),
    (models.JSONField, "json"),
    (models.URLField, "url"),
    (models.EmailField, "email"),
    (models.SlugField, "slug"),
    (models.TextField, "textarea"),
    (models.DecimalField, "number"),
    (models.FloatField, "number"),
    (models.IntegerField, "number"),
    (models.DateTimeField, "datetime"),
    (models.DateField, "date"),
]


def editable_fields(model):
    """Concrete, writable fields of `model`, in declaration order."""
    return [
        field
        for field in model._meta.concrete_fields
        if field.editable and not field.auto_created and field.name not in SKIPPED
    ]


def _widget(field) -> str:
    if field.choices:
        return "choice"
    for klass, name in _TYPES:
        if isinstance(field, klass):
            return name
    return "text"


def field_schema(model) -> list[dict]:
    """What the inspector needs to render an editor for every field on `model`."""
    schema = []
    for field in editable_fields(model):
        entry = {
            "name": field.name,
            "type": _widget(field),
            "label": str(field.verbose_name).capitalize(),
            "help": str(field.help_text),
            # A field with a default is not something the editor must supply.
            "required": not (field.blank or field.has_default() or field.null),
            "system": field.name in SYSTEM,
        }
        if field.choices:
            entry["choices"] = [{"value": v, "label": str(label)} for v, label in field.choices]
        if getattr(field, "max_length", None):
            entry["max_length"] = field.max_length
        if field.is_relation:
            entry["type"] = "relation"
            entry["relation"] = field.related_model._meta.label_lower
        schema.append(entry)
    return schema


def _to_json(field, value):
    if value is None:
        return None
    if isinstance(field, models.FileField):
        # FieldFile — the storage-relative name is the durable part; the URL is derived.
        return value.name or ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):  # datetime is a date subclass, so this covers both
        return value.isoformat()
    return value


def snapshot(obj) -> dict:
    """A JSON-safe record of every editable field on `obj`."""
    return {
        field.name: _to_json(field, field.value_from_object(obj)) for field in editable_fields(obj)
    }


def _from_json(field, value):
    if value is None:
        return None
    if isinstance(field, models.DateTimeField):
        return parse_datetime(value) if isinstance(value, str) else value
    if isinstance(field, models.DateField):
        return parse_date(value) if isinstance(value, str) else value
    return value


def assign(obj, data: dict) -> list[str]:
    """Write `data` onto `obj`, ignoring keys that are not fields. Returns the names set,
    which is what `save(update_fields=...)` wants."""
    by_name = {field.name: field for field in editable_fields(obj)}
    written = []
    for name, value in data.items():
        field = by_name.get(name)
        if field is None:
            continue
        if field.is_relation:
            setattr(obj, field.attname, value)
        else:
            setattr(obj, name, _from_json(field, value))
        written.append(name)
    return written
