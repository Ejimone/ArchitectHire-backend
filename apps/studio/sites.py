"""The Studio admin site.

Subclasses Unfold's site so we control three things Unfold leaves fixed: the
command-palette cache, the set of custom pages mounted under ``/admin/``, and the
extra context every template receives.
"""

import hashlib
from typing import Any

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import URLPattern, URLResolver
from django.utils.encoding import force_bytes
from unfold.sites import UnfoldAdminSite


class StudioAdminSite(UnfoldAdminSite):
    def extra_urls(self) -> list[URLResolver | URLPattern]:
        """Custom Studio pages. Called by ``UnfoldAdminSite._get_extra_urls()``."""
        from apps.studio.urls import studio_urls

        return studio_urls(self)

    def search(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse | HttpResponse:
        """Command-palette search, always against live data.

        Unfold caches results for five minutes keyed on (user, term). That makes a
        record saved seconds ago invisible to any term the user already searched —
        the exact failure this CMS cannot afford. Drop the entry before delegating so
        every keystroke hits the database.

        The key construction mirrors ``UnfoldAdminSite.search``; it is pinned by the
        ``django-unfold>=0.104,<0.105`` requirement in pyproject.toml.
        """
        term = (request.GET.get("s") or "").lower()
        if term:
            key_base = f"{request.user.pk}_{term}"
            digest = hashlib.sha256(force_bytes(key_base)).hexdigest()
            cache.delete(f"unfold_search_{digest}")
        return super().search(request, extra_context)
