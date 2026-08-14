from rest_framework.permissions import BasePermission


class IsStudioStaff(BasePermission):
    """Same bar the Django-admin composer uses (`apps.studio.views.StudioPageView`), so
    the two surfaces can never disagree about who may edit the site."""

    message = "Studio access requires an active staff account."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)
