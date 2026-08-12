"""Command Center metrics.

Wired in as `UNFOLD["DASHBOARD_CALLBACK"]`, so it augments the admin index context
rather than replacing the view.

The bias here is toward things the owner can *act on*. A count of published blog
posts is trivia; a count of image slots still empty is a to-do list. Every health
figure links to the screen where it gets fixed.
"""

from datetime import timedelta
from typing import Any

from django.contrib.admin.models import LogEntry
from django.db.models import Sum
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from apps.studio.publishing import draft_total


def _recent(days: int):
    return timezone.now() - timedelta(days=days)


def content_health() -> list[dict[str, Any]]:
    """Things that are wrong or unfinished, each linked to its fix."""
    from apps.cms.models import CopyBlock, MediaAsset, PageSEO
    from apps.core.scopes import STATIC_PAGE_KEYS

    empty_slots = MediaAsset.objects.filter(image="").count()
    empty_copy = CopyBlock.objects.filter(text="").count()
    drafts = draft_total()

    described = set(PageSEO.objects.values_list("page_key", flat=True))
    missing_seo = len([key for key in STATIC_PAGE_KEYS if key not in described])

    return [
        {
            "label": "Empty image slots",
            "value": empty_slots,
            "icon": "image_not_supported",
            "tone": "warn" if empty_slots else "success",
            "link": f"{reverse('admin:studio_media')}?state=empty",
            "link_label": "Fill them",
            "hint": "Placeholders with no image uploaded yet",
        },
        {
            "label": "Pages missing SEO",
            "value": missing_seo,
            "icon": "travel_explore",
            "tone": "warn" if missing_seo else "success",
            "link": reverse("admin:cms_pageseo_changelist"),
            "link_label": "Add records",
            "hint": "No title or description for search results",
        },
        {
            "label": "Waiting in draft",
            "value": drafts,
            "icon": "edit_note",
            "tone": "info" if drafts else "success",
            "link": reverse("admin:studio_queue"),
            "link_label": "Open queue",
            "hint": "Written but not live on the site",
        },
        {
            "label": "Empty copy blocks",
            "value": empty_copy,
            "icon": "format_quote",
            "tone": "warn" if empty_copy else "success",
            "link": reverse("admin:cms_copyblock_changelist"),
            "link_label": "Review",
            "hint": "Keys the frontend reads that have no text",
        },
    ]


def business_metrics() -> list[dict[str, Any]]:
    """Marketplace activity over the last week and month."""
    from apps.accounts.models import User
    from apps.engagements.models import Engagement
    from apps.orders.models import Order
    from apps.projects.models import Estimate, Project
    from apps.providers.models import Credential

    week = _recent(7)
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active_engagements = Engagement.objects.exclude(status__in=["complete", "cancelled"])
    booked = active_engagements.aggregate(total=Sum("total"))["total"] or 0
    pending_credentials = Credential.objects.filter(status="uploaded").count()

    return [
        {
            "label": "Estimates",
            "value": Estimate.objects.filter(created_at__gte=week).count(),
            "icon": "request_quote",
            "hint": "Last 7 days",
            "link": reverse("admin:projects_estimate_changelist"),
        },
        {
            "label": "Active projects",
            "value": Project.objects.exclude(status__in=["complete", "cancelled"]).count(),
            "icon": "folder_open",
            "hint": "Not complete or cancelled",
            "link": reverse("admin:projects_project_changelist"),
        },
        {
            "label": "Engagements in flight",
            "value": active_engagements.count(),
            "icon": "work",
            "hint": f"${booked:,.0f} booked",
            "link": reverse("admin:engagements_engagement_changelist"),
        },
        {
            "label": "Orders",
            "value": Order.objects.filter(created_at__gte=month_start).count(),
            "icon": "receipt_long",
            "hint": "This month",
            "link": reverse("admin:orders_order_changelist"),
        },
        {
            "label": "New users",
            "value": User.objects.filter(date_joined__gte=week).count(),
            "icon": "person_add",
            "hint": "Last 7 days",
            "link": reverse("admin:accounts_user_changelist"),
        },
        {
            "label": "Credentials to verify",
            "value": pending_credentials,
            "icon": "verified_user",
            "tone": "warn" if pending_credentials else None,
            "hint": "Uploaded, awaiting review",
            "link": f"{reverse('admin:providers_credential_changelist')}?status__exact=uploaded",
        },
    ]


def recent_activity(limit: int = 12) -> list[dict[str, Any]]:
    """The admin's own audit log, which Django records but never shows anywhere."""
    entries = LogEntry.objects.select_related("user", "content_type").order_by("-action_time")[
        :limit
    ]
    verbs = {1: ("Added", "add_circle"), 2: ("Changed", "edit"), 3: ("Deleted", "delete")}
    rows = []
    for entry in entries:
        verb, icon = verbs.get(entry.action_flag, ("Touched", "circle"))
        rows.append(
            {
                "verb": verb,
                "icon": icon,
                "object": entry.object_repr,
                "model": entry.content_type.name if entry.content_type else "",
                "user": entry.user.get_username() if entry.user else "system",
                "when": entry.action_time,
                "url": entry.get_admin_url() if entry.action_flag != 3 else None,
            }
        )
    return rows


def quick_actions() -> list[dict[str, str]]:
    return [
        {"label": "New blog post", "icon": "post_add", "url": reverse("admin:cms_blogpost_add")},
        {
            "label": "New case study",
            "icon": "auto_stories",
            "url": reverse("admin:cms_casestudy_add"),
        },
        {
            "label": "Upload media",
            "icon": "add_photo_alternate",
            "url": reverse("admin:studio_media"),
        },
        {"label": "Edit a page", "icon": "web", "url": reverse("admin:studio_pages")},
    ]


def dashboard_callback(request: HttpRequest, context: dict[str, Any]) -> dict[str, Any]:
    context.update(
        {
            "studio_health": content_health(),
            "studio_metrics": business_metrics(),
            "studio_activity": recent_activity(),
            "studio_actions": quick_actions(),
        }
    )
    return context
