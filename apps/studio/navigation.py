"""The Studio sidebar.

Django's app index groups models by the app they happen to live in, which is a fact
about the code, not about the work. Content that the owner edits together — a blog
post, its author, its category — is scattered across three apps, while `cms` alone
holds 35 unrelated models.

This module regroups all of it around tasks. Items are permission-filtered, so a
staff account with narrow rights sees a short menu rather than a wall of links it
cannot open.
"""

from collections.abc import Callable

from django.http import HttpRequest
from django.urls import reverse_lazy

from apps.studio.publishing import draft_total


def _can_view(label: str) -> Callable[[HttpRequest], bool]:
    """Permission callback for `app_label.model_name`."""
    app_label, model_name = label.split(".")

    def check(request: HttpRequest) -> bool:
        return bool(request.user.has_perm(f"{app_label}.view_{model_name}"))

    return check


def _item(title: str, icon: str, label: str, badge: str | None = None) -> dict:
    """A sidebar link to a model's changelist."""
    app_label, model_name = label.split(".")
    entry = {
        "title": title,
        "icon": icon,
        "link": reverse_lazy(f"admin:{app_label}_{model_name}_changelist"),
        "permission": _can_view(label),
    }
    if badge:
        entry["badge"] = badge
    return entry


def _group(title: str, items: list[dict], collapsible: bool = False) -> dict:
    return {"title": title, "separator": True, "collapsible": collapsible, "items": items}


# --- Badges -----------------------------------------------------------------
# Referenced by dotted path: Unfold resolves badges via import_string, not by value.


def badge_drafts(request: HttpRequest) -> str | None:
    total = draft_total()
    return str(total) if total else None


def badge_pending_credentials(request: HttpRequest) -> str | None:
    from apps.providers.models import Credential

    count = Credential.objects.filter(status="uploaded").count()
    return str(count) if count else None


def badge_empty_media_slots(request: HttpRequest) -> str | None:
    from apps.cms.models import MediaAsset

    count = MediaAsset.objects.filter(image="").count()
    return str(count) if count else None


# --- Navigation --------------------------------------------------------------


def navigation(request: HttpRequest) -> list[dict]:
    return [
        _group(
            "Overview",
            [
                {
                    "title": "Command Center",
                    "icon": "space_dashboard",
                    "link": reverse_lazy("admin:index"),
                },
                {
                    "title": "Publish queue",
                    "icon": "publish",
                    "link": reverse_lazy("admin:studio_queue"),
                    "badge": "apps.studio.navigation.badge_drafts",
                },
            ],
        ),
        _group(
            "Site content",
            [
                {
                    "title": "Pages",
                    "icon": "web",
                    "link": reverse_lazy("admin:studio_pages"),
                },
                _item("Copy blocks", "format_quote", "cms.copyblock"),
                _item("SEO", "travel_explore", "cms.pageseo"),
                _item("Navigation", "menu", "cms.navgroup"),
                _item("Footer", "bottom_panel_close", "cms.footercolumn"),
                _item("Social links", "share", "cms.sociallink"),
                _item("Site settings", "tune", "cms.sitesettings"),
            ],
        ),
        _group(
            "Editorial",
            [
                _item("Blog posts", "article", "cms.blogpost"),
                _item("Blog categories", "sell", "cms.blogcategory"),
                _item("Authors", "person_edit", "cms.author"),
                _item("Case studies", "auto_stories", "cms.casestudy"),
                _item("Case study categories", "sell", "cms.casestudycategory"),
                _item("Inspiration", "palette", "cms.inspirationitem"),
                _item("Policies", "gavel", "cms.policypage"),
            ],
        ),
        _group(
            "Media",
            [
                {
                    "title": "Media library",
                    "icon": "perm_media",
                    "link": reverse_lazy("admin:studio_media"),
                    "badge": "apps.studio.navigation.badge_empty_media_slots",
                },
            ],
        ),
        _group(
            "Page blocks",
            [
                _item("Hero carousel", "view_carousel", "cms.herocarouselslide"),
                _item("Value props", "workspace_premium", "cms.valueprop"),
                _item("Steps", "linear_scale", "cms.step"),
                _item("Stats", "insights", "cms.stat"),
                _item("FAQs", "help", "cms.faq"),
                _item("Testimonials", "reviews", "cms.testimonial"),
                _item("Case cards", "gallery_thumbnail", "cms.casecard"),
                _item("Use cases", "checklist", "cms.usecase"),
                _item("Personas", "groups", "cms.persona"),
                _item("Principles", "balance", "cms.principle"),
                _item("Trust logos", "verified", "cms.trustlogo"),
                _item("Credential badges", "military_tech", "cms.credentialbadge"),
                _item("Estimate teaser", "calculate", "cms.estimateteaseroption"),
                _item("Feature matrix", "table_rows", "cms.featurematrixrow"),
                _item("Media assets", "image", "cms.mediaasset"),
            ],
            collapsible=True,
        ),
        _group(
            "Catalog & pricing",
            [
                _item("Service categories", "category", "catalog.servicecategory"),
                _item("Services", "design_services", "catalog.service"),
                _item("Project types", "home_work", "catalog.projecttype"),
                _item("Add-ons", "add_circle", "catalog.addon"),
                _item("Plans", "list_alt", "catalog.plan"),
                _item("Render deliverables", "deployed_code", "catalog.renderdeliverable"),
                _item("Subscription plans", "loyalty", "payments.subscriptionplan"),
                _item("Drafting config", "architecture", "catalog.draftingconfig"),
                _item("Estimate config", "calculate", "catalog.estimateconfig"),
            ],
            collapsible=True,
        ),
        _group(
            "Jurisdictions",
            [
                _item("States", "map", "jurisdictions.state"),
                _item("Cities", "location_city", "jurisdictions.city"),
            ],
            collapsible=True,
        ),
        _group(
            "Operations",
            [
                _item("Projects", "folder_open", "projects.project"),
                _item("Estimates", "request_quote", "projects.estimate"),
                _item("Matches", "handshake", "projects.match"),
                _item("Orders", "receipt_long", "orders.order"),
                _item("Engagements", "work", "engagements.engagement"),
                _item("Milestones", "flag", "engagements.milestone"),
                _item("Deliverables", "inventory_2", "engagements.deliverable"),
                _item("Change requests", "edit_note", "engagements.changerequest"),
                _item("Requote flags", "priority_high", "engagements.requoteflag"),
                _item("Time entries", "schedule", "engagements.timeentry"),
                _item(
                    "Credential queue",
                    "verified_user",
                    "providers.credential",
                    badge="apps.studio.navigation.badge_pending_credentials",
                ),
            ],
            collapsible=True,
        ),
        _group(
            "People",
            [
                _item("Users", "person", "accounts.user"),
                _item("Groups", "group", "auth.group"),
                _item("Architects", "architecture", "providers.architectprofile"),
                _item("Experts", "engineering", "providers.expertprofile"),
                _item("Disciplines", "school", "providers.discipline"),
                _item("Reviews", "star_rate", "providers.review"),
                _item("Portfolio items", "photo_library", "providers.portfolioitem"),
                _item("Contact submissions", "inbox", "cms.contactsubmission"),
                _item("Newsletter", "mail", "cms.newslettersubscriber"),
            ],
            collapsible=True,
        ),
        _group(
            "Money",
            [
                _item("Subscriptions", "card_membership", "payments.subscription"),
                _item("Invoices", "receipt", "payments.subscriptioninvoice"),
                _item("Payments", "payments", "payments.paymentrecord"),
                _item("Escrow ledger", "account_balance", "payments.escrowtransaction"),
                _item("Payouts", "savings", "payments.payout"),
                _item("Payout accounts", "account_balance_wallet", "payments.payoutaccount"),
                _item("Fee policy", "percent", "payments.feepolicy"),
                _item("Webhook events", "webhook", "payments.webhookevent"),
            ],
            collapsible=True,
        ),
        _group(
            "System",
            [
                _item("Job postings", "work_history", "cms.jobposting"),
                _item("Departments", "domain", "cms.department"),
                _item("Perks", "redeem", "cms.perk"),
                _item("Contact methods", "contact_support", "cms.contactmethod"),
                _item("Contact topics", "topic", "cms.contacttopic"),
                _item("Search index", "search", "search.searchindexentry"),
                _item("Popular searches", "trending_up", "search.popularsearch"),
                _item("Notifications", "notifications", "notifications.notification"),
                _item("Push subscriptions", "notification_add", "notifications.pushsubscription"),
                _item("Threads", "forum", "messaging.thread"),
                _item("Messages", "chat", "messaging.message"),
            ],
            collapsible=True,
        ),
    ]
