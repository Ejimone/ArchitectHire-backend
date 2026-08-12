"""Reusable changelist display helpers.

Two things every content changelist needs and Django gives you neither of: a status
that reads at a glance, and a thumbnail for rows whose subject is an image. Before
this, `status` rendered as the bare string "published" and images not at all.

Label colours map onto Unfold's `@display(label=...)` variants — `success`, `info`,
`warning`, `danger`, `primary`, or `None` for neutral. Draft is deliberately neutral:
"not yet live" is the absence of a state, not a warning.
"""

from collections.abc import Callable

from django.db.models import Model
from django.utils.html import format_html
from django.utils.safestring import SafeString

# --- Status label maps -------------------------------------------------------

PUBLISH_LABELS = {"published": "success", "draft": None}

ONBOARDING_LABELS = {
    "approved": "success",
    "submitted": "info",
    "rejected": "danger",
    "draft": None,
    "in_progress": "info",
}

CREDENTIAL_LABELS = {
    "verified": "success",
    "uploaded": "warning",
    "rejected": "danger",
    "expired": "danger",
    "missing": None,
}

PAYMENT_LABELS = {
    "succeeded": "success",
    "paid": "success",
    "active": "success",
    "pending": "warning",
    "open": "warning",
    "trialing": "info",
    "processing": "info",
    "failed": "danger",
    "past_due": "danger",
    "canceled": "danger",
    "cancelled": "danger",
    "refunded": None,
}

WORKFLOW_LABELS = {
    "complete": "success",
    "hired": "success",
    "accepted": "success",
    "underway": "info",
    "in_progress": "info",
    "proposed": "info",
    "choosing_architect": "warning",
    "blocked": "danger",
    "declined": "danger",
    "rejected": "danger",
    "cancelled": "danger",
    "withdrawn": None,
}


def status_display(
    field: str = "status",
    labels: dict[str, str | None] | None = None,
    description: str = "Status",
) -> Callable:
    """Build a `@display`-decorated method rendering `field` as a coloured label.

    Returns `(raw_value, human_label)`; Unfold looks the raw value up in the label
    map for the colour and shows the human label as the text.
    """
    from unfold.decorators import display

    label_map = labels if labels is not None else PUBLISH_LABELS

    @display(description=description, ordering=field, label=label_map)
    def show(self, obj: Model) -> tuple[str, str]:
        value = getattr(obj, field, "") or ""
        getter = getattr(obj, f"get_{field}_display", None)
        return value, (getter() if getter else value)

    return show


def thumbnail_display(field: str = "image", description: str = "Preview") -> Callable:
    """Build a `@display`-decorated method rendering `field` as a small preview."""
    from unfold.decorators import display

    @display(description=description)
    def show(self, obj: Model) -> SafeString | str:
        image = getattr(obj, field, None)
        if not image:
            return "—"
        return format_html(
            '<img src="{}" alt="" loading="lazy" '
            'style="height:36px;width:56px;object-fit:cover;border-radius:4px;'
            'border:1px solid var(--studio-border)">',
            image.url,
        )

    return show


def truncated_display(field: str, length: int = 80, description: str | None = None) -> Callable:
    """Build a `@display`-decorated method showing the first `length` characters."""
    from unfold.decorators import display

    @display(description=description or field.replace("_", " ").capitalize())
    def show(self, obj: Model) -> str:
        text = getattr(obj, field, "") or ""
        return f"{text[:length]}…" if len(text) > length else (text or "—")

    return show
