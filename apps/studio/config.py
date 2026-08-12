"""The Studio design system, expressed as Unfold configuration.

Imported by ``settings.base`` as the ``UNFOLD`` setting. Everything here must be
importable before the app registry is ready, so callables are used for anything that
touches staticfiles or the URL conf.

Palette: **Graphite & Brass**. A warm-neutral base (hue 75, chroma <= 0.010) reads as
paper and graphite rather than the cool blue-grey every admin panel defaults to; the
brass accent (hue 58-82) is the single brand colour. Values are OKLCH because Unfold
emits them straight into CSS custom properties, so the whole interface — surfaces,
borders, focus rings, charts — derives from these two ramps in both themes.
"""

from django.templatetags.static import static
from django.urls import reverse_lazy

# --- Ramps ------------------------------------------------------------------

BASE = {
    "50": "oklch(98.4% .003 75)",
    "100": "oklch(96.5% .005 75)",
    "200": "oklch(92.2% .007 75)",
    "300": "oklch(86.0% .008 75)",
    "400": "oklch(70.5% .009 75)",
    "500": "oklch(57.0% .010 75)",
    "600": "oklch(46.5% .010 75)",
    "700": "oklch(38.5% .010 75)",
    "800": "oklch(28.5% .009 75)",
    "900": "oklch(21.5% .008 75)",
    "950": "oklch(15.5% .007 75)",
}

PRIMARY = {
    "50": "oklch(97.5% .020 82)",
    "100": "oklch(94.5% .040 82)",
    "200": "oklch(89.0% .070 80)",
    "300": "oklch(82.5% .100 78)",
    "400": "oklch(75.5% .125 74)",
    "500": "oklch(68.5% .140 70)",
    "600": "oklch(60.0% .135 66)",
    "700": "oklch(50.0% .115 62)",
    "800": "oklch(41.0% .092 60)",
    "900": "oklch(34.5% .072 58)",
    "950": "oklch(23.0% .050 58)",
}

# Text sits one step further from the surface than Unfold's defaults: on a warm base
# the stock pairings drop under 4.5:1 for body copy.
FONT = {
    "subtle-light": "var(--color-base-600)",
    "subtle-dark": "var(--color-base-400)",
    "default-light": "var(--color-base-800)",
    "default-dark": "var(--color-base-200)",
    "important-light": "var(--color-base-950)",
    "important-dark": "var(--color-base-50)",
}


UNFOLD = {
    "SITE_TITLE": "ArchitectHire Studio",
    "SITE_HEADER": "ArchitectHire",
    "SITE_SUBHEADER": "Studio",
    "SITE_URL": None,
    "SITE_SYMBOL": "architecture",
    "SITE_ICON": lambda request: static("studio/mark.svg"),
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "sizes": "32x32",
            "type": "image/svg+xml",
            "href": lambda _: static("studio/mark.svg"),
        },
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "SHOW_BACK_BUTTON": True,
    "SHOW_LANGUAGES": False,
    "BORDER_RADIUS": "6px",
    "COLORS": {"base": BASE, "primary": PRIMARY, "font": FONT},
    "STYLES": [lambda request: static("studio/studio.css")],
    "SCRIPTS": [lambda request: static("studio/studio.js")],
    "DASHBOARD_CALLBACK": "apps.studio.dashboard.dashboard_callback",
    "LOGIN": {
        "redirect_after": lambda request: reverse_lazy("admin:index"),
    },
    "COMMAND": {
        # search_models stays off: apps.studio.search covers the same models with
        # richer labels, and leaving both on returns every hit twice.
        "search_models": False,
        "show_history": True,
        "search_callback": "apps.studio.search.omnisearch",
    },
    "SIDEBAR": {
        "show_search": False,  # Superseded by the command palette.
        "show_all_applications": True,
        "navigation": "apps.studio.navigation.navigation",
    },
}
