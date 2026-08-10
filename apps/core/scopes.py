"""Central registry of page-scope keys used by CMS scoped blocks (FAQ, Stat, Step, ...).

A scope is either a static page key ("landing", "services") or a parameterized key
("project-type:adu", "city:oakland", "state:CA"). Scoped-block models validate against
this registry so admin content always lands on a real page.
"""

import re

from django.core.exceptions import ValidationError

# Static marketing/app surfaces (mirrors design/README.md page inventory).
STATIC_PAGE_KEYS = [
    "landing",
    "services-landing",
    "services",
    "3d-visualization",
    "cad-drafting",
    "architect-landing",
    "for-experts",
    "projects",
    "cities",
    "blog",
    "case-studies",
    "about",
    "careers",
    "contact",
    "privacy",
    "terms",
    "inspiration",
    "jurisdiction-database",
    "search",
    "get-started",
    "order-render",
    "order-drafting",
]

# Parameterized scope prefixes -> slug pattern.
DYNAMIC_SCOPE_PATTERNS = {
    "project-type": r"[a-z0-9-]+",
    "city": r"[a-z0-9-]+",
    "state": r"[A-Z]{2}|DC|PR",
    "service": r"[a-z0-9-]+",
    "blog-post": r"[a-z0-9-]+",
    "case-study": r"[a-z0-9-]+",
}


def is_valid_scope(value: str) -> bool:
    if value in STATIC_PAGE_KEYS:
        return True
    prefix, sep, param = value.partition(":")
    if not sep:
        return False
    pattern = DYNAMIC_SCOPE_PATTERNS.get(prefix)
    return bool(pattern and re.fullmatch(pattern, param))


def validate_scope(value: str) -> None:
    if not is_valid_scope(value):
        examples = ", ".join(STATIC_PAGE_KEYS[:5])
        raise ValidationError(
            f"'{value}' is not a valid scope. Use a page key ({examples}, ...) or a "
            f"parameterized key like 'project-type:adu', 'city:oakland', 'state:CA'."
        )


def static_scope_choices():
    return [(key, key) for key in STATIC_PAGE_KEYS]
