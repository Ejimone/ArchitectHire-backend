"""Draft/published state across every content model.

`PublishableModel` is abstract and inherited by ~20 models spread over cms and
catalog. Discovering them from the app registry keeps the Publish Queue, the sidebar
badge and the dashboard in agreement, and means a new content model joins all three
the moment it inherits the base — no registry to remember to update.
"""

from dataclasses import dataclass

from django.apps import apps
from django.db.models import Model, QuerySet
from django.urls import reverse

from apps.core.models import PublishableModel


@dataclass(frozen=True)
class DraftGroup:
    """Pending drafts for one model, ready to render."""

    model: type[Model]
    label: str
    count: int
    changelist_url: str

    @property
    def model_label(self) -> str:
        """`app_label.modelname` — the value the publish form posts back."""
        return self.model._meta.label_lower

    @property
    def objects(self) -> QuerySet:
        return draft_queryset(self.model)


def publishable_models() -> list[type[Model]]:
    """Every concrete model inheriting `PublishableModel`, in a stable order."""
    return sorted(
        (
            model
            for model in apps.get_models()
            if issubclass(model, PublishableModel) and not model._meta.abstract
        ),
        key=lambda model: model._meta.label_lower,
    )


def draft_queryset(model: type[Model]) -> QuerySet:
    return model._default_manager.filter(status=PublishableModel.Status.DRAFT)


def draft_groups(include_empty: bool = False) -> list[DraftGroup]:
    """Per-model draft counts, heaviest first — the Publish Queue's data source."""
    groups = []
    for model in publishable_models():
        count = draft_queryset(model).count()
        if not count and not include_empty:
            continue
        meta = model._meta
        groups.append(
            DraftGroup(
                model=model,
                label=str(meta.verbose_name_plural).capitalize(),
                count=count,
                changelist_url=reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist"),
            )
        )
    return sorted(groups, key=lambda group: (-group.count, group.label))


def draft_total() -> int:
    return sum(draft_queryset(model).count() for model in publishable_models())
