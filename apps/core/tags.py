"""Which frontend cache tags a written row invalidates.

The frontend attaches ``["cms", ...specific]`` to every fetch it makes, so purging
"cms" drops the whole site while purging "cms:blog:adu-permits" drops one post. This
module is the single place that decides how narrow a given write may be, and the
vocabulary below is a contract shared with the frontend's revalidate route — the two
must be changed together.

Anything unrecognised collapses to the catch-all rather than to nothing: over-purging
costs one rebuild, under-purging serves stale content until the next unrelated write.
"""

from apps.cms.models import ScopedBlock

CATCH_ALL = "cms"
# The one scope that is not a page: NavigationView and FooterView both splice its copy
# into their own payloads, so its edits have to reach the chrome tags as well.
CHROME_SCOPE = "chrome"
CHROME_TAGS = {"cms:nav", "cms:footer"}


def _page(scope: str) -> str:
    return f"cms:page:{scope}"


def _scoped(scope: str) -> set[str]:
    tags = {_page(scope)}
    if scope == CHROME_SCOPE:
        tags |= CHROME_TAGS
    return tags


def _media_scope(slot_key: str) -> str:
    """Slot keys are ``<scope>:<slot-name>`` and the scope may itself contain a colon
    (``city:oakland:work-1``), so split from the right — as `validate_slot_key` does."""
    return slot_key.rpartition(":")[0]


def _blog(slug: str) -> set[str]:
    return {"cms:blog", f"cms:blog:{slug}"}


def _case(slug: str) -> set[str]:
    return {"cms:cases", f"cms:case:{slug}"}


# Keyed by `Model._meta.label_lower`. Models absent here fall through to the scoped
# block / whole-app / catch-all rules in `tags_for`.
_TAGS_BY_MODEL = {
    # Site chrome. Settings reach every page, so they carry the catch-all too.
    "cms.sitesettings": lambda obj: {CATCH_ALL, "cms:settings"},
    "cms.navgroup": lambda obj: {"cms:nav"},
    "cms.navitem": lambda obj: {"cms:nav"},
    "cms.footercolumn": lambda obj: {"cms:footer"},
    "cms.footerlink": lambda obj: {"cms:footer"},
    "cms.sociallink": lambda obj: {"cms:footer"},
    # Page-scoped content that is not a ScopedBlock.
    "cms.copyblock": lambda obj: _scoped(obj.scope),
    "cms.pageseo": lambda obj: _scoped(obj.page_key),
    "cms.mediaasset": lambda obj: _scoped(_media_scope(obj.slot_key)),
    # Editorial.
    "cms.author": lambda obj: {"cms:blog"},
    "cms.blogcategory": lambda obj: {"cms:blog"},
    "cms.blogpost": lambda obj: _blog(obj.slug),
    "cms.blogcontentblock": lambda obj: _blog(obj.post.slug),
    "cms.casestudycategory": lambda obj: {"cms:cases"},
    "cms.casestudy": lambda obj: _case(obj.slug),
    "cms.casestudyimage": lambda obj: _case(obj.case_study.slug),
    "cms.policypage": lambda obj: {f"cms:policies:{obj.slug}"},
    "cms.policysection": lambda obj: {f"cms:policies:{obj.page.slug}"},
    "cms.department": lambda obj: {"cms:careers"},
    "cms.jobposting": lambda obj: {"cms:careers"},
    "cms.perk": lambda obj: {"cms:careers"},
    "cms.contactmethod": lambda obj: {"cms:contact"},
    "cms.contacttopic": lambda obj: {"cms:contact"},
    "cms.inspirationitem": lambda obj: {"cms:inspiration"},
    # Inbound rows change no rendered content, but the app-wide signal wiring fires
    # for them all the same. Tag them at their own surface so a contact form the
    # public can submit at will can never trigger a site-wide purge.
    "cms.contactsubmission": lambda obj: {"cms:contact"},
    "cms.newslettersubscriber": lambda obj: {"cms:contact"},
    "cms.inspirationlike": lambda obj: {"cms:inspiration"},
    # Catalog. Project types own a marketing page each; plans are a list endpoint.
    "catalog.projecttype": lambda obj: {
        "cms:catalog",
        f"cms:catalog:project-type:{obj.slug}",
        _page(f"project-type:{obj.slug}"),
    },
    "catalog.plan": lambda obj: {"cms:catalog", "cms:catalog:plans"},
    # Jurisdictions. Both carry a page of their own as well as the database views.
    "jurisdictions.state": lambda obj: {
        "cms:jurisdictions",
        f"cms:jurisdictions:state:{obj.code}",
        _page(f"state:{obj.code}"),
    },
    "jurisdictions.city": lambda obj: {
        "cms:jurisdictions",
        f"cms:jurisdictions:city:{obj.slug}",
        _page(f"city:{obj.slug}"),
    },
    "payments.subscriptionplan": lambda obj: {"cms:plans"},
}

# Everything else in these apps feeds pricing and the jurisdiction database wholesale.
_TAGS_BY_APP = {
    "catalog": {"cms:catalog"},
    "jurisdictions": {"cms:jurisdictions"},
}


def tags_for(instance) -> set[str]:
    """The frontend cache tags a write to `instance` invalidates."""
    meta = instance._meta
    handler = _TAGS_BY_MODEL.get(meta.label_lower)
    if handler is not None:
        return handler(instance)
    # The 14 block types in cms.views.BLOCK_REGISTRY are interchangeable here: each
    # one only ever renders on the page named by its scope.
    if isinstance(instance, ScopedBlock):
        return {_page(instance.scope)}
    app_tags = _TAGS_BY_APP.get(meta.app_label)
    if app_tags is not None:
        return set(app_tags)
    return {CATCH_ALL}
