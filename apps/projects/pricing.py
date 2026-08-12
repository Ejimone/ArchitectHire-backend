"""The instant-quote engine — exact port of design/app/Get Started.dc.html.

Six branches hang off the quiz's opening fork; each one prices differently but
returns the *same* presentation shape so the frontend can render any of them
with one component and never do arithmetic of its own.

``design`` — the fixed-quote curve (unchanged, and still the only branch with a
jurisdiction multiplier)::

    rate  = rate_base + rate_coeff * exp(-sqft / rate_decay_sqft)   # $/sf
    base  = round(sqft * rate / round_to) * round_to
    mult  = multiplier_floor + (score / 100) * multiplier_span
    total = (base + selected addon prices) * mult
    range = total ± range_pct%

``drafting``      as-built max($2,500, round(sf·0.25/50)·50) · PDF-to-CAD sheets·$30
                  · else hours·$78; +$1,500 stamp; +25% rush on (base + stamp)
``consult``       flat $145 / $150 / $250
``viz``           walkthrough secs·$50 · 3D floor plan qty·$100 · else qty·$99
``scan``          max($500, round(area·psf/10)·10), psf $0.50 Scan-to-BIM else $0.20
``engineering``   structural stamp $1,500 · Title-24 $300 · code consulting hrs·$150

Design-branch constants live in catalog.EstimateConfig and catalog.Addon; the
drafting constants in catalog.DraftingConfig — all owner-tunable. The consult,
viz, scan and engineering rates are module constants (the design has no config
surface for them yet). Floats mirror the design's JS arithmetic exactly,
including its half-up rounding; results are quantized to cents when persisted.
"""

import math
from dataclasses import dataclass, field

from apps.catalog.models import Addon, DraftingConfig, EstimateConfig
from apps.jurisdictions.models import State

GOALS = ("design", "drafting", "consult", "viz", "scan", "engineering")

# Row tones. The design hard-codes hex (#232c57 / #135bff / #8b93b5); the API
# names the intent instead and the frontend maps it onto the brand tokens.
TONE_DEFAULT = "default"
TONE_ACCENT = "accent"
TONE_MUTED = "muted"

# Quiz vocabularies (design: buildFlow's option lists). Anything the user can
# pick is enumerated here so the API validates it instead of trusting the client.
BEDS_OPTIONS = ["Studio", "1", "2", "3", "4", "5+"]
BATHS_OPTIONS = ["1", "1.5", "2", "2.5", "3", "4+"]
STORIES_OPTIONS = ["1 story", "2 stories", "3+"]
STYLE_OPTIONS = [
    "Modern",
    "Contemporary",
    "Farmhouse",
    "Craftsman",
    "Mediterranean",
    "Traditional",
    "Not sure yet",
]
BUDGET_OPTIONS = [
    "Under $250k",
    "$250k – $500k",
    "$500k – $1M",
    "$1M – $2M",
    "$2M+",
    "Not sure yet",
]
SITE_OPTIONS = ["Yes, I own it", "In escrow / closing", "Still shopping"]
ROOM_KEYS = [
    "kitchen",
    "primaryBath",
    "guestBath",
    "living",
    "bedrooms",
    "basement",
    "garage",
    "outdoor",
]
DRAFTING_SERVICES = ["CAD drafting", "2D as-built package", "PDF-to-CAD", "Redline cleanup"]
DRAFTING_HAVE_OPTIONS = ["Sketch or dims", "PDFs / scans", "Existing CAD"]
VIZ_HAVE_OPTIONS = ["CAD / model", "2D plans", "Sketch or photos"]
CONSULT_TYPES = ["Video consult", "Plan review & markup", "Feasibility check"]
CONSULT_PRICES = {"Video consult": 145, "Plan review & markup": 150, "Feasibility check": 250}
VIZ_TYPES = ["Single render", "3D floor plan", "Walkthrough"]
VIZ_WALKTHROUGH_PER_SEC = 50
VIZ_FLOOR_PLAN_EACH = 100
VIZ_RENDER_EACH = 99
SCAN_TYPES = ["3D laser scanning", "Scan-to-BIM"]
SCAN_PSF = {"Scan-to-BIM": 0.5, "3D laser scanning": 0.2}
SCAN_ROUND_TO = 10
SCAN_MINIMUM = 500
ENGINEERING_TYPES = ["Structural stamp", "Title-24 / energy", "Code consulting"]
ENGINEERING_FLAT = {"Structural stamp": 1500, "Title-24 / energy": 300}
ENGINEERING_HOURLY_RATE = 150

# The design's initial answer state — a partial answer set still prices, exactly
# as the prototype does when a deep link jumps the user past the opening fork.
DEFAULT_ANSWERS = {
    "ptype": "Residential",
    "scope": "New custom home",
    "sqft": 2400,
    "timeline": "Standard (10–12 wks)",
    "beds": "3",
    "baths": "2",
    "stories": "2 stories",
    "style": "Modern",
    "rooms": {
        "kitchen": True,
        "primaryBath": True,
        "living": True,
        "guestBath": False,
        "bedrooms": False,
        "basement": False,
        "garage": False,
        "outdoor": False,
    },
    "budget": "$500k – $1M",
    "site": "Yes, I own it",
    "addons": ["structural", "viz"],
    "service": "CAD drafting",
    "hours": 8,
    "dsqft": 1500,
    "sheets": 6,
    "stamp": False,
    "have": "Sketch or dims",
    "rush": False,
    "consultType": "Video consult",
    "vizType": "Single render",
    "vizQty": 1,
    "vizSecs": 30,
    "vizHave": "CAD / model",
    "engType": "Structural stamp",
    "engHours": 4,
    "scanType": "3D laser scanning",
    "scanArea": 2500,
}

ROOMSY_SCOPES = ["New custom home", "Addition", "ADU"]
RENO_SCOPES = ["Renovation", "Kitchen / bath"]
ADDON_PROSE = {
    "structural": "structural coordination",
    "mep": "MEP drawings",
    "viz": "3D visualization",
    "energy": "energy calcs",
}


def round_half_up(value: float) -> int:
    """JS ``Math.round`` — half away from zero, not Python's banker's rounding."""
    return math.floor(value + 0.5)


def money(value: float) -> str:
    """The design's ``fmt()``: ``'$' + Math.round(n).toLocaleString()``."""
    return f"${round_half_up(value):,}"


def _row(label: str, sub: str, val: str, tone: str = TONE_DEFAULT) -> dict:
    return {"label": label, "sub": sub, "val": val, "tone": tone}


@dataclass
class EstimateResult:
    sqft: int
    rate: float
    base: float
    addon_total: float
    addons: dict[str, bool]
    multiplier: float
    total: float
    low: float
    high: float
    jurisdiction: dict = field(default_factory=dict)


@dataclass
class Quote:
    """One priced branch: the numbers we persist plus the view the design renders."""

    goal: str
    project_type: str
    scope: str
    sqft: int
    timeline: str
    addons: dict[str, bool]
    rate: float
    base: float
    addon_total: float
    multiplier: float
    total: float
    low: float
    high: float
    view: dict


def compute_estimate(*, sqft: int, state: State, addon_keys: list[str]) -> EstimateResult:
    config = EstimateConfig.get_solo()

    rate = config.rate_base + config.rate_coeff * math.exp(-sqft / config.rate_decay_sqft)
    base = round((sqft * rate) / config.round_to) * config.round_to

    all_addons = {addon.key: addon for addon in Addon.objects.all()}
    selected = {key: (key in addon_keys) for key in all_addons}
    addon_total = float(sum(all_addons[key].price for key in addon_keys if key in all_addons))

    multiplier = config.multiplier_floor + (state.complexity_score / 100) * config.multiplier_span
    total = (base + addon_total) * multiplier
    spread = config.range_pct / 100

    return EstimateResult(
        sqft=sqft,
        rate=rate,
        base=base,
        addon_total=addon_total,
        addons=selected,
        multiplier=multiplier,
        total=total,
        low=total * (1 - spread),
        high=total * (1 + spread),
        jurisdiction={
            "code": state.code,
            "name": state.name,
            "score": state.complexity_score,
            "band": state.band_label,
            "multiplier": round(multiplier, 3),
            "factors": state.factors,
        },
    )


# --------------------------------------------------------------------------- #
# Branch quotes                                                                #
# --------------------------------------------------------------------------- #


def _juris_view(state: State) -> dict:
    """The jurisdiction score card (design branch only)."""
    return {
        "code": state.code,
        "name": state.name,
        "score": state.complexity_score,
        "band": state.band_label,
        "multiplier": round(state.multiplier, 3),
        "factors": state.factors,
    }


def _design_program(a: dict) -> tuple[bool, bool, str, str]:
    residential = a["ptype"] != "Commercial"
    roomsy = residential and a["scope"] in ROOMSY_SCOPES
    style_word = f"{a['style']} " if residential and a["style"] not in ("", "Not sure yet") else ""
    bed_word = "studio" if a["beds"] == "Studio" else f"{a['beds']}-bed"
    prog = (
        f"{bed_word} / {a['baths']}-bath {style_word}{a['scope'].lower()}"
        if roomsy
        else f"{style_word}{a['scope'].lower()}"
    )
    return residential, roomsy, style_word, prog


def _design_quote(a: dict, state: State) -> Quote:
    addon_keys = list(a["addons"])
    result = compute_estimate(sqft=a["sqft"], state=state, addon_keys=addon_keys)
    _, roomsy, style_word, prog = _design_program(a)

    rows = [
        _row(
            "Base drawing set",
            f"{a['sqft']:,} sf · ${result.rate:.2f}/sf",
            money(result.base),
        )
    ]
    for addon in Addon.objects.all():
        if addon.key in addon_keys:
            rows.append(_row(addon.label, addon.sub, money(float(addon.price))))
    rows.append(
        _row(
            "Jurisdiction multiplier",
            f"{state.name} complexity",
            f"×{result.multiplier:.2f}",
            TONE_ACCENT,
        )
    )

    budget_word = f" Build budget {a['budget']}." if a["budget"] not in ("", "Not sure yet") else ""
    saved_line = (
        f"{prog} · {a['sqft']:,} sf · {state.name}"
        if roomsy
        else f"{a['scope']} · {a['sqft']:,} sf · {state.name}"
    )
    view = {
        "headline": f"Your {style_word}{a['scope'].lower()} in {state.name}",
        "sub": (
            "A typical price range for a project like yours, itemized. "
            "Your architect sets their own final price."
        ),
        "totalLabel": "TYPICAL PRICE RANGE",
        "headlineTotal": f"{money(result.low)} – {money(result.high)}",
        "total": money(result.total),
        "totalRowLabel": "Typical range",
        "rows": rows,
        "footnote": (
            "A guide, not a quote. Architects set their own rates — "
            "you agree the final price with them directly."
        ),
        "showJuris": True,
        "juris": _juris_view(state),
        "cta": "See my architect matches →",
        "savedLine": saved_line,
        "match": {
            "tag": "ARCHITECT",
            "role": "A licensed architect",
            "blurb": f"Licensed in {state.name}, experienced with a {prog}.{budget_word}",
        },
        "matches": [
            {
                "tag": "ARCHITECT",
                "role": f"Licensed architect · {state.name}",
                "blurb": (
                    f"Pre-cleared on {state.name} jurisdiction experience and matched to a {prog}."
                ),
            }
        ],
        "matchRoleShort": "2–3 licensed architects",
    }
    return Quote(
        goal="design",
        project_type=a["ptype"],
        scope=a["scope"],
        sqft=a["sqft"],
        timeline=a["timeline"],
        addons=result.addons,
        rate=result.rate,
        base=result.base,
        addon_total=result.addon_total,
        multiplier=result.multiplier,
        total=result.total,
        low=result.low,
        high=result.high,
        view=view,
    )


def _drafting_quote(a: dict, state: State) -> Quote:
    config = DraftingConfig.get_solo()
    rate = float(config.hourly_rate)
    psf = float(config.asbuilt_per_sf)
    asbuilt_min = float(config.asbuilt_minimum)
    per_sheet = float(config.per_sheet)
    stamp_fee = float(config.stamp_fee)
    rush_pct = config.rush_pct / 100

    service = a["service"]
    approx = False
    if service == "2D as-built package":
        base = max(asbuilt_min, round_half_up(a["dsqft"] * psf / 50) * 50)
        base_sub = f"{a['dsqft']:,} sf · ${psf:.2f}/sf (min {money(asbuilt_min)})"
        size_line = f"{a['dsqft']:,} sf"
        size = a["dsqft"]
    elif service == "PDF-to-CAD":
        base = a["sheets"] * per_sheet
        base_sub = f"{a['sheets']} sheets · {money(per_sheet)}/sheet"
        size_line = f"{a['sheets']} sheets"
        size = a["sheets"]
    else:
        base = a["hours"] * rate
        base_sub = f"{a['hours']} hrs · {money(rate)}/hr (US)"
        size_line = f"{a['hours']} hrs"
        size = a["hours"]
        approx = True

    stamp_amount = stamp_fee if a["stamp"] else 0.0
    rush_amount = (base + stamp_amount) * rush_pct if a["rush"] else 0.0
    total = base + stamp_amount + rush_amount
    speed_short = "Rush · 24–48h" if a["rush"] else "Standard · 2–5 days"
    total_str = f"~{money(total)}" if approx else money(total)

    rows = [_row(service, base_sub, money(base))]
    if a["stamp"]:
        rows.append(
            _row(
                "Licensed stamp",
                "Pro licensed in your jurisdiction (matched separately)",
                f"from {money(stamp_fee)}",
            )
        )
    rows.append(
        _row(
            "Turnaround",
            speed_short,
            f"+{money(rush_amount)}" if a["rush"] else "—",
            TONE_DEFAULT if a["rush"] else TONE_MUTED,
        )
    )

    matches = [
        {
            "tag": "DRAFTER",
            "role": "A vetted CAD drafter",
            "blurb": (
                f"Matched to your {service.lower()} — you approve scope and pay them directly."
            ),
        }
    ]
    if a["stamp"]:
        matches.append(
            {
                "tag": "ARCHITECT",
                "role": "A licensed architect",
                "blurb": "Reviews and stamps the finished set in your jurisdiction.",
            }
        )

    view = {
        "headline": service,
        "sub": (
            "Your instant price, itemized. Hourly work is tracked on-platform; "
            "flat jobs are locked before work starts."
        ),
        "totalLabel": "ESTIMATED TOTAL",
        "headlineTotal": total_str,
        "total": total_str,
        "totalRowLabel": "Estimated total",
        "rows": rows,
        "footnote": (
            "You pay your drafter directly at their rate — we don’t take a cut of the work."
        ),
        "showJuris": False,
        "juris": None,
        "cta": "See my drafter + architect →" if a["stamp"] else "See my drafter match →",
        "savedLine": f"{service} · {size_line} · {speed_short}",
        "match": {
            "tag": "DRAFTER + PRO" if a["stamp"] else "DRAFTER",
            "role": "A drafter + a licensed pro" if a["stamp"] else "A vetted CAD drafter",
            "blurb": (
                "A drafter builds the set; a licensed architect stamps it as a separate step."
                if a["stamp"]
                else f"Matched to your {service.lower()}, ready to confirm scope within a day."
            ),
        },
        "matches": matches,
        "matchRoleShort": "a drafter and a licensed pro" if a["stamp"] else "a CAD drafter",
    }
    return Quote(
        goal="drafting",
        project_type=a["ptype"],
        scope=service,
        sqft=size,
        timeline=speed_short,
        addons={"stamp": bool(a["stamp"]), "rush": bool(a["rush"])},
        rate=rate if approx else 0.0,
        base=base,
        addon_total=stamp_amount + rush_amount,
        multiplier=1.0,
        total=total,
        low=total,
        high=total,
        view=view,
    )


def _consult_quote(a: dict, state: State) -> Quote:
    consult_type = a["consultType"]
    base = float(CONSULT_PRICES.get(consult_type, CONSULT_PRICES["Video consult"]))
    view = {
        "headline": consult_type,
        "sub": "A flat, upfront rate — book it and meet your pro.",
        "totalLabel": "FLAT RATE",
        "headlineTotal": money(base),
        "total": money(base),
        "totalRowLabel": "Total",
        "rows": [_row(consult_type, f"{a['ptype']} · {state.name}", money(base))],
        "footnote": "A flat rate agreed before you meet — no surprises.",
        "showJuris": False,
        "juris": None,
        "cta": "See my match →",
        "savedLine": f"{consult_type} · {a['ptype']} · {state.name}",
        "match": {
            "tag": "CONSULT",
            "role": f"A licensed architect · {state.name}",
            "blurb": (
                f"Available for a {consult_type.lower()} on your {a['ptype'].lower()} project."
            ),
        },
        "matches": [
            {
                "tag": "CONSULT",
                "role": f"Licensed architect · {state.name}",
                "blurb": f"Set up for your {consult_type.lower()}.",
            }
        ],
        "matchRoleShort": "a licensed architect",
    }
    return Quote(
        goal="consult",
        project_type=a["ptype"],
        scope=consult_type,
        sqft=0,
        timeline="",
        addons={},
        rate=0.0,
        base=base,
        addon_total=0.0,
        multiplier=1.0,
        total=base,
        low=base,
        high=base,
        view=view,
    )


def _viz_quote(a: dict, state: State) -> Quote:
    viz_type = a["vizType"]
    if viz_type == "Walkthrough":
        base = float(a["vizSecs"] * VIZ_WALKTHROUGH_PER_SEC)
        base_sub = f"{a['vizSecs']} sec · {money(VIZ_WALKTHROUGH_PER_SEC)}/sec"
        size_line = f"{a['vizSecs']} sec"
        size = a["vizSecs"]
    elif viz_type == "3D floor plan":
        base = float(a["vizQty"] * VIZ_FLOOR_PLAN_EACH)
        plural = "s" if a["vizQty"] > 1 else ""
        base_sub = f"{a['vizQty']} plan{plural} · {money(VIZ_FLOOR_PLAN_EACH)} each"
        size_line = f"{a['vizQty']} plan{plural}"
        size = a["vizQty"]
    else:
        base = float(a["vizQty"] * VIZ_RENDER_EACH)
        plural = "s" if a["vizQty"] > 1 else ""
        base_sub = f"{a['vizQty']} render{plural} · {money(VIZ_RENDER_EACH)} each"
        size_line = f"{a['vizQty']} render{plural}"
        size = a["vizQty"]

    view = {
        "headline": viz_type,
        "sub": "Your instant price. Adjust the exact deliverable list with your artist.",
        "totalLabel": "ESTIMATED TOTAL",
        "headlineTotal": money(base),
        "total": money(base),
        "totalRowLabel": "Estimated total",
        "rows": [
            _row(viz_type, base_sub, money(base)),
            _row("Starting from", a["vizHave"], "—", TONE_MUTED),
        ],
        "footnote": "Typical turnaround 3–7 days. You pay your visualization artist directly.",
        "showJuris": False,
        "juris": None,
        "cta": "See my 3D artist →",
        "savedLine": f"{viz_type} · {size_line} · from {a['vizHave']}",
        "match": {
            "tag": "3D",
            "role": "A 3D visualization artist",
            "blurb": (
                f"Matched to your {viz_type.lower()}, working from your {a['vizHave'].lower()}."
            ),
        },
        "matches": [
            {
                "tag": "3D",
                "role": "3D visualization artist",
                "blurb": f"Set up for your {viz_type.lower()}.",
            }
        ],
        "matchRoleShort": "a 3D artist",
    }
    return Quote(
        goal="viz",
        project_type=a["ptype"],
        scope=viz_type,
        sqft=size,
        timeline="",
        addons={},
        rate=0.0,
        base=base,
        addon_total=0.0,
        multiplier=1.0,
        total=base,
        low=base,
        high=base,
        view=view,
    )


def _scan_quote(a: dict, state: State) -> Quote:
    scan_type = a["scanType"]
    psf = SCAN_PSF.get(scan_type, SCAN_PSF["3D laser scanning"])
    base = float(
        max(SCAN_MINIMUM, round_half_up(a["scanArea"] * psf / SCAN_ROUND_TO) * SCAN_ROUND_TO)
    )
    role = "A scan-to-BIM modeler" if scan_type == "Scan-to-BIM" else "A reality-capture specialist"
    view = {
        "headline": scan_type,
        "sub": (
            "Your instant price, based on area captured. "
            "Crew confirms access and scope before scheduling."
        ),
        "totalLabel": "ESTIMATED TOTAL",
        "headlineTotal": money(base),
        "total": money(base),
        "totalRowLabel": "Estimated total",
        "rows": [
            _row(scan_type, f"{a['scanArea']:,} sf · ${psf:.2f}/sf", money(base)),
            _row("Location", state.name, "—", TONE_MUTED),
        ],
        "footnote": (
            "A guide, not a quote — access, detail level, and travel can adjust the final price."
        ),
        "showJuris": False,
        "juris": None,
        "cta": "See my scanning match →",
        "savedLine": f"{scan_type} · {a['scanArea']:,} sf · {state.name}",
        "match": {
            "tag": "SCAN / BIM",
            "role": role,
            "blurb": f"Set up to capture {a['scanArea']:,} sf in {state.name}.",
        },
        "matches": [
            {
                "tag": "SCAN / BIM",
                "role": f"{role.replace('A ', '', 1)} · {state.name}",
                "blurb": f"Matched for your {scan_type.lower()}.",
            }
        ],
        "matchRoleShort": "a reality-capture specialist",
    }
    return Quote(
        goal="scan",
        project_type=a["ptype"],
        scope=scan_type,
        sqft=a["scanArea"],
        timeline="",
        addons={},
        rate=psf,
        base=base,
        addon_total=0.0,
        multiplier=1.0,
        total=base,
        low=base,
        high=base,
        view=view,
    )


def _engineering_quote(a: dict, state: State) -> Quote:
    eng_type = a["engType"]
    if eng_type == "Code consulting":
        base = float(a["engHours"] * ENGINEERING_HOURLY_RATE)
        base_sub = f"{a['engHours']} hrs · {money(ENGINEERING_HOURLY_RATE)}/hr"
        size_line = f"{a['engHours']} hrs"
        size = a["engHours"]
        role = "A code consultant"
        tag = "CODE"
    elif eng_type == "Title-24 / energy":
        base = float(ENGINEERING_FLAT[eng_type])
        base_sub = "Energy compliance · flat, from"
        size_line = "Title-24 calcs"
        size = 0
        role = "A Title-24 energy consultant"
        tag = "ENERGY"
    else:
        base = float(ENGINEERING_FLAT["Structural stamp"])
        base_sub = "Review & stamp · flat, from"
        size_line = "structural stamp"
        size = 0
        role = "A licensed structural engineer"
        tag = "ENGINEER"

    view = {
        "headline": eng_type,
        "sub": (
            "Your instant price. Compliance work is matched to a pro "
            "licensed for your jurisdiction."
        ),
        "totalLabel": "ESTIMATED TOTAL",
        "headlineTotal": money(base),
        "total": money(base),
        "totalRowLabel": "Estimated total",
        "rows": [
            _row(eng_type, base_sub, money(base)),
            _row("Jurisdiction", f"{state.name} · {state.band_label.lower()}", "—", TONE_MUTED),
        ],
        "footnote": (
            "A guide, not a quote — the engineer confirms scope and their rate before starting."
        ),
        "showJuris": False,
        "juris": None,
        "cta": "See my engineer →",
        "savedLine": f"{eng_type} · {size_line} · {state.name}",
        "match": {
            "tag": tag,
            "role": role,
            "blurb": (f"Licensed for work in {state.name} and set up for your {eng_type.lower()}."),
        },
        "matches": [
            {
                "tag": tag,
                "role": f"{role.replace('A ', '', 1)} · {state.name}",
                "blurb": f"Matched for your {eng_type.lower()}.",
            }
        ],
        "matchRoleShort": "a licensed engineer",
    }
    return Quote(
        goal="engineering",
        project_type=a["ptype"],
        scope=eng_type,
        sqft=size,
        timeline="",
        addons={},
        rate=0.0,
        base=base,
        addon_total=0.0,
        multiplier=1.0,
        total=base,
        low=base,
        high=base,
        view=view,
    )


BRANCH_QUOTES = {
    "design": _design_quote,
    "drafting": _drafting_quote,
    "consult": _consult_quote,
    "viz": _viz_quote,
    "scan": _scan_quote,
    "engineering": _engineering_quote,
}


# --------------------------------------------------------------------------- #
# Brief (the summary phase's generated prose + fact grid)                      #
# --------------------------------------------------------------------------- #


def _design_brief(a: dict, state: State, paras: list, facts: list) -> None:
    residential, roomsy, style_word, _ = _design_program(a)
    reno = residential and a["scope"] in RENO_SCOPES
    bed_word = "a studio" if a["beds"] == "Studio" else f"a {a['beds']}-bedroom"

    p1 = f"You're planning a {style_word}{a['scope'].lower()} in {state.name}"
    if roomsy:
        stories = (
            ", single story"
            if a["stories"] == "1 story"
            else " over two stories"
            if a["stories"] == "2 stories"
            else " over three-plus stories"
        )
        p1 += f" — {bed_word}, {a['baths']}-bath home{stories}"
    p1 += f", roughly {a['sqft']:,} sf."
    paras.append(p1)

    ctx = []
    if a["budget"] not in ("", "Not sure yet"):
        ctx.append(f"a construction budget around {a['budget']}")
    if roomsy and a["scope"] == "New custom home":
        ctx.append(
            "and you already own the lot"
            if a["site"] == "Yes, I own it"
            else "and the lot is under contract"
            if a["site"] == "In escrow / closing"
            else "and you're still choosing a lot"
        )
    p2 = ""
    if reno:
        picked = [key for key, on in a["rooms"].items() if on]
        if picked:
            p2 += (
                f"The remodel covers {len(picked)} area"
                f"{'s' if len(picked) > 1 else ''} of the home. "
            )
    p2 += f"You're targeting a {a['timeline'].lower()} timeline"
    if ctx:
        p2 += f" with {', '.join(ctx)}"
    p2 += "."
    paras.append(p2)

    add_on = [ADDON_PROSE[key] for key in ADDON_PROSE if key in a["addons"]]
    p3 = "We'll assemble a permit-ready drawing set"
    if add_on:
        p3 += f" including {', '.join(add_on)}"
    p3 += (
        f", matched to an architect licensed in {state.name}. "
        "Here's your estimate and who we'd pair you with."
    )
    paras.append(p3)

    facts.append(("Project", f"{a['ptype']} · {a['scope']}"))
    if roomsy:
        beds = "Studio" if a["beds"] == "Studio" else f"{a['beds']} BR"
        facts.append(("Program", f"{beds} · {a['baths']} BA · {a['stories']}"))
    if residential:
        facts.append(("Style", a["style"]))
    facts.append(("Size", f"{a['sqft']:,} sf"))
    facts.append(("Budget", a["budget"]))
    if roomsy and a["scope"] == "New custom home":
        facts.append(("Lot", a["site"]))
    facts.append(("Timeline", a["timeline"]))
    facts.append(("Location", state.name))


def _split_facts(saved_line: str, labels: list[str], facts: list) -> None:
    """The design splits ``savedLine`` on ' · ' and labels the pieces positionally."""
    for index, value in enumerate(saved_line.split(" · ")):
        facts.append((labels[index] if index < len(labels) else "Detail", value))


def build_brief(*, goal: str, answers: dict, state: State, view: dict) -> dict:
    """Port of the design's ``summaryFor(a, est)`` — prose + the fact grid."""
    a = answers
    paras: list[str] = []
    facts: list[tuple[str, str]] = []

    if goal == "design":
        _design_brief(a, state, paras, facts)
    elif goal == "drafting":
        stamp_clause = ", with a licensed stamp added as a separate step" if a["stamp"] else ""
        paras.append(f"You need {a['service'].lower()}{stamp_clause}.")
        paras.append(
            f"We'll match you with {view['matchRoleShort']}; you'll approve scope "
            "and see the number before any work starts."
        )
        _split_facts(view["savedLine"], ["Service", "Size", "Turnaround"], facts)
    elif goal == "consult":
        paras.append(
            f"You'd like a {a['consultType'].lower()} for your "
            f"{a['ptype'].lower()} project in {state.name}."
        )
        paras.append(
            "We'll set you up with a licensed architect for that session at a flat, upfront rate."
        )
        facts += [
            ("Service", a["consultType"]),
            ("Project", a["ptype"]),
            ("Location", state.name),
        ]
    elif goal == "viz":
        paras.append(f"You want {a['vizType'].lower()} built from your {a['vizHave'].lower()}.")
        paras.append(
            "We'll match you with a 3D visualization artist and lock the deliverable list up front."
        )
        _split_facts(view["savedLine"], ["Deliverable", "Quantity", "From"], facts)
    elif goal == "scan":
        paras.append(
            f"You need {a['scanType'].lower()} for about {a['scanArea']:,} sf in {state.name}."
        )
        paras.append(
            "We'll dispatch a reality-capture crew near you and confirm access before scheduling."
        )
        facts += [
            ("Service", a["scanType"]),
            ("Area", f"{a['scanArea']:,} sf"),
            ("Location", state.name),
        ]
    else:
        hours = f" (about {a['engHours']} hrs)" if a["engType"] == "Code consulting" else ""
        paras.append(f"You need {a['engType'].lower()}{hours} for a project in {state.name}.")
        paras.append(
            "We'll match you with a pro licensed for your jurisdiction "
            "and confirm scope before starting."
        )
        facts += [("Service", a["engType"]), ("Location", state.name)]

    return {"paras": paras, "facts": [{"k": k, "v": v} for k, v in facts if v]}


def compute_quote(*, goal: str, answers: dict, state: State) -> Quote:
    """Price one branch and build its view — the single entry point for the API."""
    merged = {**DEFAULT_ANSWERS, **answers}
    quote = BRANCH_QUOTES[goal](merged, state)
    quote.view["summary"] = build_brief(goal=goal, answers=merged, state=state, view=quote.view)
    return quote
