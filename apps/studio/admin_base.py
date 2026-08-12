"""Shared admin base classes.

Every ModelAdmin in the project inherits from one of these instead of importing
`django.contrib.admin.ModelAdmin` directly, so presentation defaults are set in one
place rather than repeated across 72 registrations.
"""

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db import models
from import_export.admin import ImportExportModelAdmin as BaseImportExportModelAdmin
from solo.admin import SingletonModelAdmin as BaseSingletonModelAdmin
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.forms.widgets import WysiwygWidget
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminTextareaWidget

__all__ = [
    "StudioImportExportAdmin",
    "StudioModelAdmin",
    "StudioSingletonAdmin",
    "StudioStackedInline",
    "StudioTabularInline",
    "StudioUserAdmin",
    "WysiwygWidget",
]


class StudioModelAdmin(ModelAdmin):
    """Base for every model admin in the project.

    Defaults chosen for a content-editing tool rather than a database browser:
    filters live in a side sheet with an explicit Apply button (long filter lists on
    `scope`/`group` are unusable as instant-reload links), and navigating away from a
    dirty form warns instead of silently discarding edits.
    """

    list_filter_submit = True
    list_filter_sheet = True
    warn_unsaved_form = True

    formfield_overrides = {
        models.TextField: {"widget": UnfoldAdminTextareaWidget},
    }


class StudioSingletonAdmin(BaseSingletonModelAdmin, ModelAdmin):
    """django-solo singletons (SiteSettings, DraftingConfig, EstimateConfig).

    `SingletonModelAdmin` must precede Unfold's `ModelAdmin` in the MRO so its
    changelist-to-changeform redirect and add/delete permission overrides win, while
    Unfold still supplies the rendering.
    """

    warn_unsaved_form = True


class StudioImportExportAdmin(BaseImportExportModelAdmin, ModelAdmin):
    """Models with CSV/XLSX import-export (Service, State, City).

    Requires `unfold.contrib.import_export` in INSTALLED_APPS, which supplies the
    styled import/export templates and form widgets.
    """

    list_filter_submit = True
    warn_unsaved_form = True


class StudioUserAdmin(BaseUserAdmin, ModelAdmin):
    """The user admin.

    Django's `UserAdmin` hardcodes its own forms and the read-only password-hash
    widget, all of which render unstyled outside Unfold. Swapping in Unfold's
    equivalents is the only way to get a consistent change form here.
    """

    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    warn_unsaved_form = True


class StudioTabularInline(TabularInline):
    tab = True


class StudioStackedInline(StackedInline):
    tab = True
