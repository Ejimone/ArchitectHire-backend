"""Extract seed data from the design prototypes into seeds/*.json.

The design's .dc.html files hardcode every price, state score, nav item, etc.
This script parses those JS literals so the database seeds match the design
exactly (pinpoint accuracy, zero placeholders). Re-run after design updates:

    uv run python scripts/extract_seeds.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "design"
SEEDS = ROOT / "seeds"
SEEDS.mkdir(exist_ok=True)


def slugify(value: str) -> str:
    value = value.lower().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def map_href(href: str) -> str:
    """Design-file links -> real frontend routes."""
    href = href.strip()
    mapping = {
        "Landing.dc.html": "/",
        "Services Landing.dc.html": "/services-landing",
        "Services.dc.html": "/services",
        "3D Visualization.dc.html": "/services/3d-visualization",
        "CAD Drafting.dc.html": "/services/cad-drafting",
        "Architect Landing.dc.html": "/for-architects",
        "For Experts.dc.html": "/for-experts",
        "Project Landing.dc.html": "/projects/backyard-adu",
        "Projects.dc.html": "/projects",
        "City Landing.dc.html": "/cities/oakland",
        "Cities.dc.html": "/cities",
        "Blog.dc.html": "/guides",
        "Blog Post.dc.html": "/guides",
        "Case Studies.dc.html": "/case-studies",
        "Case Study.dc.html": "/case-studies",
        "About.dc.html": "/about",
        "Careers.dc.html": "/careers",
        "Contact.dc.html": "/contact",
        "Privacy.dc.html": "/privacy",
        "Inspiration.dc.html": "/inspiration",
        "Jurisdiction Database.dc.html": "/jurisdictions",
        "State Permit Guide.dc.html": "/jurisdictions/ca",
        "Search.dc.html": "/search",
    }
    base, _, anchor = href.partition("#")
    base = base.replace("../app/", "").replace("../marketing/", "")
    # Longest names first: "Project Landing.dc.html" must not match "Landing.dc.html".
    for design_name in sorted(mapping, key=len, reverse=True):
        if base.endswith(design_name):
            return mapping[design_name] + (f"#{anchor}" if anchor else "")
    app_mapping = {
        "Get Started.dc.html": "/get-started",
        "Order Render.dc.html": "/order/render",
        "Order Drafting.dc.html": "/order/drafting",
        "Matches.dc.html": "/matches",
        "Engagement.dc.html": "/engagement",
        "Account.dc.html": "/account",
        "Architect Account.dc.html": "/pro",
        "Expert Account.dc.html": "/pro/expert",
    }
    for design_name, route in app_mapping.items():
        if base.endswith(design_name):
            return route + (f"#{anchor}" if anchor else "")
    return href


def read(rel: str) -> str:
    return (DESIGN / rel).read_text(encoding="utf-8")


def extract_jurisdictions() -> list[dict]:
    text = read("marketing/Jurisdiction Database.dc.html")
    rows = re.findall(r"\['([^']+)','([A-Z]{2})',(\d+),'([^']+)','([^']+)'\]", text)
    return [
        {"name": name, "code": code, "score": int(score), "region": region, "largest_city": city}
        for name, code, score, region, city in rows
    ]


def extract_services() -> list[dict]:
    text = read("marketing/Services.dc.html")
    groups = []
    group_pattern = re.compile(
        r"\{ name:'([^']+)', icon:icons\.(\w+), tagline:'([^']+)', "
        r"hasDetail:(true|false), detailHref:'([^']*)',\s*services:\[(.*?)\]\}",
        re.S,
    )
    service_pattern = re.compile(r"S\('([^']+)','([^']+)','([^']+)','([^']+)'(?:,'([^']*)')?\)")
    for m in group_pattern.finditer(text):
        name, icon, tagline, has_detail, detail_href, body = m.groups()
        services = [
            {
                "name": s[0],
                "description": s[1],
                "price_display": s[2],
                "price_unit": s[3],
                "detail_href": map_href(s[4]) if s[4] else "",
                "slug": slugify(s[0]),
            }
            for s in service_pattern.findall(body)
        ]
        groups.append(
            {
                "name": name,
                "slug": slugify(name),
                "icon": icon,
                "tagline": tagline,
                "has_detail": has_detail == "true",
                "detail_href": map_href(detail_href) if has_detail == "true" else "",
                "services": services,
            }
        )
    return groups


def extract_project_types() -> list[dict]:
    text = read("marketing/Projects.dc.html")
    groups = []
    group_pattern = re.compile(r"\{ name:'([^']+)', note:'([^']+)', items:\[(.*?)\]\},?\s*\n", re.S)
    item_pattern = re.compile(
        r"\{ name:'([^']+)', sub:'([^']+)', price:'([^']+)', slotId:'([^']+)', ph:'([^']+)'"
    )
    for m in group_pattern.finditer(text):
        name, note, body = m.groups()
        items = [
            {
                "name": i[0],
                "sub": i[1],
                "price_display": i[2],
                "slot_id": i[3],
                "image_hint": i[4],
                "slug": slugify(i[0]),
            }
            for i in item_pattern.findall(body)
        ]
        groups.append({"group": name, "note": note, "items": items})
    return groups


def extract_cities() -> list[dict]:
    text = read("marketing/Cities.dc.html")
    pattern = re.compile(
        r"\{ name:'([^']+)', state:'([^']+)', count:'([^']+)', slotId:'([^']+)', ph:'([^']+)'"
    )
    return [
        {
            "name": m[0],
            "state": m[1],
            "architect_count": m[2],
            "slot_id": m[3],
            "image_hint": m[4],
            "slug": slugify(m[0]),
        }
        for m in pattern.findall(text)
    ]


def extract_addons() -> list[dict]:
    text = read("app/Get Started.dc.html")
    pattern = re.compile(r"\{key:'(\w+)',label:'([^']+)',sub:'([^']+)',price:(\d+)\}")
    return [
        {"key": m[0], "label": m[1], "sub": m[2], "price": int(m[3])} for m in pattern.findall(text)
    ]


def extract_render_matrix() -> list[dict]:
    text = read("app/Order Render.dc.html")
    pattern = re.compile(
        r"'([^']+)':\{ Conceptual:(\d+), Professional:(\d+), Photoreal:(\d+), unit:'(\w+)' \}"
    )
    return [
        {
            "deliverable": m[0],
            "conceptual": int(m[1]),
            "professional": int(m[2]),
            "photoreal": int(m[3]),
            "unit": m[4],
        }
        for m in pattern.findall(text)
    ]


def extract_plans() -> list[dict]:
    text = read("marketing/Landing.dc.html")
    pattern = re.compile(
        r"\{ key:'(\w+)', tag:'([^']+)', title:'([^']+)', blurb:'([^']+)',(.*?)\},?\s*\n", re.S
    )
    plans = []
    for m in pattern.finditer(text):
        key, tag, title, blurb, rest = m.groups()
        points = re.findall(r"'([^']{10,})'", rest)
        cta = re.search(r"cta:'([^']+)'", rest)
        plans.append(
            {
                "key": key,
                "tag": tag,
                "title": title,
                "blurb": blurb,
                "points": [p for p in points if not p.startswith("#")][:4],
                "cta_label": cta.group(1) if cta else "",
                "is_recommended": key == "fixed",
            }
        )
    return plans


def _parse_link_triples(body: str) -> list[dict]:
    return [
        {"label": t[0], "price_hint": t[1], "href": map_href(t[2])}
        for t in re.findall(r"\['([^']+)',\s*'([^']*)',\s*'([^']+)'\]", body)
    ]


def _parse_link_pairs(body: str) -> list[dict]:
    return [
        {"label": p[0], "href": map_href(p[1])}
        for p in re.findall(r"\['([^']+)',\s*'([^']+)'\]", body)
    ]


def extract_nav() -> dict:
    text = read("marketing/site-nav.js")
    svc_block = re.search(r"var SVC = \[(.*?)\n  \];", text, re.S)
    groups = []
    if svc_block:
        for gm in re.finditer(r"\{ name: '([^']+)', items: \[(.*?)\]\}", svc_block.group(1), re.S):
            groups.append({"heading": gm.group(1), "items": _parse_link_triples(gm.group(2))})
    prj_block = re.search(r"var PROJECTS = \[(.*?)\n  \];", text, re.S)
    projects = []
    if prj_block:
        projects = _parse_link_triples(prj_block.group(1)) or _parse_link_pairs(prj_block.group(1))
    loc_block = re.search(r"var CITIES = \[(.*?)\n  \];", text, re.S)
    locations = _parse_link_pairs(loc_block.group(1)) if loc_block else []
    # The prototype links every item to the same one-record template page; the real
    # site deep-links each item to its own slug.
    for item in projects:
        item["href"] = f"/projects/{slugify(item['label'])}"
    for item in locations:
        item["href"] = f"/cities/{slugify(item['label'].split(',')[0])}"
    return {"services": groups, "projects": projects, "locations": locations}


def extract_footer() -> dict:
    text = read("marketing/site-footer.js")
    cols_block = re.search(r"var COLS = \[(.*?)\n  \];", text, re.S)
    columns = []
    if cols_block:
        for cm in re.finditer(r"\{ h: '([^']+)', items: \[(.*?)\]\}", cols_block.group(1), re.S):
            columns.append({"heading": cm.group(1), "links": _parse_link_pairs(cm.group(2))})
    social = [
        {"platform": s[0], "url": s[1]} for s in re.findall(r"\['(\w+)', '(https?://[^']+)'", text)
    ]
    return {"columns": columns, "social": social}


def main():
    outputs = {
        "jurisdictions.json": extract_jurisdictions(),
        "services.json": extract_services(),
        "project_types.json": extract_project_types(),
        "cities.json": extract_cities(),
        "addons.json": extract_addons(),
        "render_matrix.json": extract_render_matrix(),
        "plans.json": extract_plans(),
        "nav.json": extract_nav(),
        "footer.json": extract_footer(),
        "drafting_config.json": {
            # design/app/Order Drafting.dc.html L229 (verified)
            "hourly_rate": 78,
            "asbuilt_per_sf": 0.25,
            "asbuilt_minimum": 2500,
            "per_sheet": 30,
            "stamp_fee": 1500,
            "rush_pct": 25,
        },
        "estimate_config.json": {
            # design/app/Get Started.dc.html estimate engine (verified)
            "rate_base": 3.2,
            "rate_coeff": 5.3,
            "rate_decay_sqft": 2600,
            "round_to": 50,
            "multiplier_floor": 1.05,
            "multiplier_span": 0.35,
            "range_pct": 8,
        },
    }
    for filename, data in outputs.items():
        path = SEEDS / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        count = len(data) if isinstance(data, list) else len(data.keys())
        print(f"{filename}: {count} entries")  # noqa: T201


if __name__ == "__main__":
    main()
