"""URL patterns for Studio's custom admin pages.

Mounted by :meth:`apps.studio.sites.StudioAdminSite.extra_urls`, so every path here
lives under ``/admin/``. Class-based pages are wrapped in ``admin_view()`` (staff
only, redirect to the admin login otherwise); the function views carry
``staff_member_required`` themselves.
"""

from django.contrib.admin import AdminSite
from django.urls import URLPattern, URLResolver, path


def studio_urls(site: AdminSite) -> list[URLResolver | URLPattern]:
    from apps.studio import views

    def page(route: str, view: type, name: str) -> URLPattern:
        return path(route, site.admin_view(view.as_view(admin_site=site)), name=name)

    return [
        page("studio/pages/", views.PageListView, "studio_pages"),
        page("studio/pages/<path:page_key>/", views.PageComposerView, "studio_page_composer"),
        page("studio/media/", views.MediaLibraryView, "studio_media"),
        page("studio/media/upload/", views.MediaUploadView, "studio_media_upload"),
        path("studio/media/sync/", views.media_sync, name="studio_media_sync"),
        page("studio/queue/", views.PublishQueueView, "studio_queue"),
        path("studio/queue/publish/", views.queue_publish, name="studio_queue_publish"),
    ]
