"""Exact-value tests for the five non-design quiz branches.

Every pinned number is read straight off design/app/Get Started.dc.html's
``computeEstimate`` (lines ~514–599) and its ``summaryFor`` (~602–659). Where the
design is wrong we pin the wrong answer on purpose and say so — see
``TestDesignBugs`` at the bottom.
"""

import pytest
from django.core.management import call_command

from apps.jurisdictions.models import State
from apps.projects.pricing import compute_quote, money, round_half_up


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--all")


@pytest.fixture
def ca(seeded):
    return State.objects.get(code="CA")


def quote(goal, state, **answers):
    return compute_quote(goal=goal, answers=answers, state=state)


def test_round_half_up_matches_js_math_round():
    # Python's round() is banker's: round(2.5) == 2. The design's Math.round is not.
    assert round_half_up(2.5) == 3
    assert round_half_up(3.5) == 4
    assert round_half_up(2.4) == 2
    assert money(1234.5) == "$1,235"


@pytest.mark.django_db
class TestDraftingBranch:
    """RATE 78 · PSF 0.25 · ASBUILT_MIN 2500 · SHEET 30 · STAMP 1500 · rush +25%."""

    def test_hourly_is_approximate(self, ca):
        q = quote("drafting", ca, service="CAD drafting", hours=8)
        assert q.total == 8 * 78 == 624
        assert q.view["headlineTotal"] == "~$624"
        assert q.view["rows"][0]["sub"] == "8 hrs · $78/hr (US)"
        assert q.view["rows"][-1]["val"] == "—"
        assert q.view["savedLine"] == "CAD drafting · 8 hrs · Standard · 2–5 days"

    def test_redline_cleanup_also_prices_hourly(self, ca):
        assert quote("drafting", ca, service="Redline cleanup", hours=40).total == 3120

    def test_pdf_to_cad_is_per_sheet(self, ca):
        q = quote("drafting", ca, service="PDF-to-CAD", sheets=6)
        assert q.total == 180
        assert q.view["headlineTotal"] == "$180"  # flat work: no "~"
        assert q.view["rows"][0]["sub"] == "6 sheets · $30/sheet"
        assert quote("drafting", ca, service="PDF-to-CAD", sheets=40).total == 1200

    def test_asbuilt_is_per_sf_over_a_2500_floor(self, ca):
        q = quote("drafting", ca, service="2D as-built package", dsqft=1500)
        assert q.total == 2500
        assert q.view["rows"][0]["sub"] == "1,500 sf · $0.25/sf (min $2,500)"

    def test_stamp_adds_1500(self, ca):
        q = quote("drafting", ca, service="CAD drafting", hours=8, stamp=True)
        assert q.total == 624 + 1500 == 2124
        assert q.view["rows"][1]["label"] == "Licensed stamp"
        assert q.view["rows"][1]["val"] == "from $1,500"
        assert q.view["cta"] == "See my drafter + architect →"
        assert [m["tag"] for m in q.view["matches"]] == ["DRAFTER", "ARCHITECT"]
        assert q.view["matchRoleShort"] == "a drafter and a licensed pro"

    def test_rush_is_25pct_of_base_plus_stamp(self, ca):
        q = quote("drafting", ca, service="CAD drafting", hours=8, stamp=True, rush=True)
        assert q.base == 624
        assert q.addon_total == 1500 + 531  # stamp + rush
        assert q.total == 2655
        assert q.view["headlineTotal"] == "~$2,655"
        assert q.view["rows"][2]["sub"] == "Rush · 24–48h"
        assert q.view["rows"][2]["val"] == "+$531"

    def test_rush_without_stamp(self, ca):
        q = quote("drafting", ca, service="PDF-to-CAD", sheets=10, rush=True)
        assert q.total == 300 + 75 == 375
        assert len(q.view["rows"]) == 2  # no stamp row

    def test_brief(self, ca):
        q = quote("drafting", ca, service="PDF-to-CAD", sheets=6, stamp=True)
        paras = q.view["summary"]["paras"]
        assert paras[0] == "You need pdf-to-cad, with a licensed stamp added as a separate step."
        assert paras[1].startswith("We'll match you with a drafter and a licensed pro;")


@pytest.mark.django_db
class TestConsultBranch:
    """Flat rates: video $145 · plan review $150 · feasibility $250."""

    @pytest.mark.parametrize(
        ("consult_type", "price"),
        [("Video consult", 145), ("Plan review & markup", 150), ("Feasibility check", 250)],
    )
    def test_flat_rates(self, ca, consult_type, price):
        q = quote("consult", ca, consultType=consult_type)
        assert q.total == q.base == q.low == q.high == price
        assert q.view["headlineTotal"] == money(price)
        assert q.view["totalLabel"] == "FLAT RATE"
        assert q.view["rows"] == [
            {
                "label": consult_type,
                "sub": "Residential · California",
                "val": money(price),
                "tone": "default",
            }
        ]

    def test_unknown_type_falls_back_to_the_video_rate(self, ca):
        assert compute_quote(goal="consult", answers={"consultType": "?"}, state=ca).total == 145

    def test_brief(self, ca):
        q = quote("consult", ca, consultType="Feasibility check", ptype="Commercial")
        assert q.view["summary"]["paras"][0] == (
            "You'd like a feasibility check for your commercial project in California."
        )
        assert q.view["summary"]["facts"] == [
            {"k": "Service", "v": "Feasibility check"},
            {"k": "Project", "v": "Commercial"},
            {"k": "Location", "v": "California"},
        ]


@pytest.mark.django_db
class TestVizBranch:
    """Walkthrough secs·$50 · 3D floor plan qty·$100 · everything else qty·$99."""

    def test_walkthrough_per_second(self, ca):
        q = quote("viz", ca, vizType="Walkthrough", vizSecs=30)
        assert q.total == 1500
        assert q.view["rows"][0]["sub"] == "30 sec · $50/sec"
        assert q.view["savedLine"] == "Walkthrough · 30 sec · from CAD / model"
        assert quote("viz", ca, vizType="Walkthrough", vizSecs=120).total == 6000

    def test_floor_plans_pluralise(self, ca):
        assert quote("viz", ca, vizType="3D floor plan", vizQty=1).view["rows"][0]["sub"] == (
            "1 plan · $100 each"
        )
        q = quote("viz", ca, vizType="3D floor plan", vizQty=3)
        assert q.total == 300
        assert q.view["rows"][0]["sub"] == "3 plans · $100 each"

    def test_stills_are_99_each(self, ca):
        assert quote("viz", ca, vizType="Single render", vizQty=1).total == 99
        q = quote("viz", ca, vizType="Single render", vizQty=10)
        assert q.total == 990
        assert q.view["rows"][0]["sub"] == "10 renders · $99 each"
        assert q.view["rows"][1] == {
            "label": "Starting from",
            "sub": "CAD / model",
            "val": "—",
            "tone": "muted",
        }

    def test_brief(self, ca):
        q = quote("viz", ca, vizType="Single render", vizQty=2, vizHave="2D plans")
        assert q.view["summary"]["paras"][0] == "You want single render built from your 2d plans."
        assert q.view["summary"]["facts"] == [
            {"k": "Deliverable", "v": "Single render"},
            {"k": "Quantity", "v": "2 renders"},
            {"k": "From", "v": "from 2D plans"},
        ]


@pytest.mark.django_db
class TestScanBranch:
    """psf $0.50 for Scan-to-BIM else $0.20; max($500, round(area·psf/10)·10)."""

    def test_laser_scanning_at_20_cents(self, ca):
        q = quote("scan", ca, scanType="3D laser scanning", scanArea=10000)
        assert q.total == 2000
        assert q.view["rows"][0]["sub"] == "10,000 sf · $0.20/sf"
        assert q.view["match"]["role"] == "A reality-capture specialist"
        assert q.view["matches"][0]["role"] == "reality-capture specialist · California"

    def test_scan_to_bim_at_50_cents(self, ca):
        q = quote("scan", ca, scanType="Scan-to-BIM", scanArea=2500)
        assert q.total == 1250
        assert q.view["rows"][0]["sub"] == "2,500 sf · $0.50/sf"
        assert q.view["match"]["role"] == "A scan-to-BIM modeler"
        assert quote("scan", ca, scanType="Scan-to-BIM", scanArea=50000).total == 25000

    def test_500_minimum(self, ca):
        assert quote("scan", ca, scanType="3D laser scanning", scanArea=500).total == 500
        assert quote("scan", ca, scanType="3D laser scanning", scanArea=2500).total == 500
        assert quote("scan", ca, scanType="Scan-to-BIM", scanArea=500).total == 500

    def test_unknown_type_falls_back_to_the_laser_rate(self, ca):
        q = compute_quote(goal="scan", answers={"scanType": "?", "scanArea": 10000}, state=ca)
        assert q.total == 2000

    def test_brief(self, ca):
        q = quote("scan", ca, scanType="Scan-to-BIM", scanArea=7500)
        assert q.view["summary"]["paras"][0] == (
            "You need scan-to-bim for about 7,500 sf in California."
        )
        assert q.view["summary"]["facts"][1] == {"k": "Area", "v": "7,500 sf"}


@pytest.mark.django_db
class TestEngineeringBranch:
    """Structural stamp $1,500 · Title-24 $300 · code consulting hrs·$150."""

    def test_structural_stamp(self, ca):
        q = quote("engineering", ca, engType="Structural stamp")
        assert q.total == 1500
        assert q.view["rows"][0]["sub"] == "Review & stamp · flat, from"
        assert q.view["match"]["tag"] == "ENGINEER"
        assert q.view["savedLine"] == "Structural stamp · structural stamp · California"

    def test_title_24(self, ca):
        q = quote("engineering", ca, engType="Title-24 / energy")
        assert q.total == 300
        assert q.view["rows"][0]["sub"] == "Energy compliance · flat, from"
        assert q.view["match"]["tag"] == "ENERGY"
        assert q.view["match"]["role"] == "A Title-24 energy consultant"

    def test_code_consulting_is_hourly(self, ca):
        q = quote("engineering", ca, engType="Code consulting", engHours=4)
        assert q.total == 600
        assert q.view["rows"][0]["sub"] == "4 hrs · $150/hr"
        assert q.view["match"]["tag"] == "CODE"
        assert quote("engineering", ca, engType="Code consulting", engHours=20).total == 3000

    def test_jurisdiction_row_but_no_score_card(self, ca):
        q = quote("engineering", ca, engType="Structural stamp")
        assert q.view["showJuris"] is False
        assert q.view["juris"] is None
        assert q.view["rows"][1] == {
            "label": "Jurisdiction",
            "sub": "California · high complexity",
            "val": "—",
            "tone": "muted",
        }

    def test_brief(self, ca):
        q = quote("engineering", ca, engType="Code consulting", engHours=6)
        assert q.view["summary"]["paras"][0] == (
            "You need code consulting (about 6 hrs) for a project in California."
        )
        assert quote("engineering", ca, engType="Title-24 / energy").view["summary"]["paras"][
            0
        ] == "You need title-24 / energy for a project in California."


@pytest.mark.django_db
class TestDesignBranchView:
    """The design branch is unchanged arithmetic — this pins its rendered shape."""

    def test_headline_band_matches_the_design(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="New custom home",
            sqft=2400,
            timeline="Standard (10–12 wks)",
            addons=["structural", "viz"],
        )
        assert q.base == 12750
        assert q.multiplier == pytest.approx(1.337)
        assert q.total == pytest.approx(22662.15, abs=0.01)
        assert q.view["headlineTotal"] == "$20,849 – $24,475"
        assert q.view["total"] == "$22,662"
        assert [row["label"] for row in q.view["rows"]] == [
            "Base drawing set",
            "Structural coordination",
            "3D visualization",
            "Jurisdiction multiplier",
        ]
        assert q.view["rows"][0]["sub"] == "2,400 sf · $5.31/sf"
        assert q.view["rows"][-1]["val"] == "×1.34"
        assert q.view["showJuris"] is True
        assert q.view["juris"]["score"] == 82
        assert len(q.view["juris"]["factors"]) == 5

    def test_new_custom_home_brief(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="New custom home",
            sqft=2400,
            timeline="Standard (10–12 wks)",
            addons=["structural", "viz"],
            beds="4",
            baths="2.5",
            stories="2 stories",
            style="Farmhouse",
            budget="$1M – $2M",
            site="In escrow / closing",
        )
        paras = q.view["summary"]["paras"]
        assert paras[0] == (
            "You're planning a Farmhouse new custom home in California — a 4-bedroom, "
            "2.5-bath home over two stories, roughly 2,400 sf."
        )
        assert paras[1] == (
            "You're targeting a standard (10–12 wks) timeline with a construction budget "
            "around $1M – $2M, and the lot is under contract."
        )
        assert paras[2] == (
            "We'll assemble a permit-ready drawing set including structural coordination, "
            "3D visualization, matched to an architect licensed in California. "
            "Here's your estimate and who we'd pair you with."
        )
        assert q.view["summary"]["facts"] == [
            {"k": "Project", "v": "Residential · New custom home"},
            {"k": "Program", "v": "4 BR · 2.5 BA · 2 stories"},
            {"k": "Style", "v": "Farmhouse"},
            {"k": "Size", "v": "2,400 sf"},
            {"k": "Budget", "v": "$1M – $2M"},
            {"k": "Lot", "v": "In escrow / closing"},
            {"k": "Timeline", "v": "Standard (10–12 wks)"},
            {"k": "Location", "v": "California"},
        ]

    def test_studio_single_story_owned_lot(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="ADU",
            sqft=600,
            timeline="Rush (6–8 wks)",
            addons=[],
            beds="Studio",
            baths="1",
            stories="1 story",
            style="Not sure yet",
            budget="Not sure yet",
            site="Yes, I own it",
        )
        paras = q.view["summary"]["paras"]
        assert paras[0] == (
            "You're planning a adu in California — a studio, 1-bath home, single story, "
            "roughly 600 sf."
        )
        assert paras[1] == "You're targeting a rush (6–8 wks) timeline."
        assert paras[2].startswith("We'll assemble a permit-ready drawing set, matched to")
        assert q.view["savedLine"] == "studio / 1-bath adu · 600 sf · California"
        assert q.view["match"]["blurb"] == (
            "Licensed in California, experienced with a studio / 1-bath adu."
        )

    def test_three_plus_stories_and_still_shopping(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="New custom home",
            sqft=5200,
            timeline="Flexible (14+ wks)",
            addons=["mep", "energy"],
            stories="3+",
            site="Still shopping",
        )
        assert " over three-plus stories" in q.view["summary"]["paras"][0]
        assert q.view["summary"]["paras"][1].endswith("and you're still choosing a lot.")
        assert "including MEP drawings, energy calcs" in q.view["summary"]["paras"][2]

    def test_renovation_counts_the_rooms(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="Renovation",
            sqft=1800,
            timeline="Standard (10–12 wks)",
            addons=[],
            rooms={"kitchen": True, "primaryBath": True, "garage": False},
        )
        assert q.view["summary"]["paras"][1].startswith("The remodel covers 2 areas of the home.")
        assert q.view["savedLine"] == "Renovation · 1,800 sf · California"

    def test_single_room_renovation_is_singular(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Residential",
            scope="Kitchen / bath",
            sqft=400,
            timeline="Standard (10–12 wks)",
            addons=[],
            rooms={"kitchen": True},
        )
        assert q.view["summary"]["paras"][1].startswith("The remodel covers 1 area of the home.")

    def test_commercial_drops_style_and_program(self, ca):
        q = quote(
            "design",
            ca,
            ptype="Commercial",
            scope="Tenant improvement",
            sqft=3000,
            timeline="Standard (10–12 wks)",
            addons=[],
        )
        assert q.view["headline"] == "Your tenant improvement in California"
        facts = {f["k"] for f in q.view["summary"]["facts"]}
        assert "Style" not in facts and "Program" not in facts


@pytest.mark.django_db
class TestDesignBugs:
    """Two faults carried over from the design, implemented as designed."""

    def test_asbuilt_psf_label_is_unreachable(self, ca):
        """BUG 1 — the as-built slider tops out at 6,000 sf, so 6,000 × $0.25 =
        $1,500 never clears the $2,500 floor. Every as-built quote in the flow
        is exactly $2,500 and the advertised "$0.25/sf" can never apply."""
        for dsqft in (400, 1500, 3000, 6000):  # the slider's full 400–6,000 range
            q = quote("drafting", ca, service="2D as-built package", dsqft=dsqft)
            assert q.total == 2500
            assert q.view["rows"][0]["sub"].endswith("$0.25/sf (min $2,500)")
        # It would take 10,000 sf — off the end of the slider — to beat the floor.
        assert quote("drafting", ca, service="2D as-built package", dsqft=6000).base == 2500

    def test_viz_keeps_only_the_cheapest_tier_and_drops_rush(self, ca):
        """BUG 2 — the quiz's viz branch replaces the 5×3 quality-tier matrix
        (catalog.RenderDeliverable) with three flat unit rates and has no rush
        surcharge at all. $99/still even undercuts the matrix's cheapest row."""
        from apps.catalog.models import RenderDeliverable

        cheapest = min(float(row.conceptual) for row in RenderDeliverable.objects.all())
        assert cheapest == 100  # 3D floor plan, Conceptual tier
        assert quote("viz", ca, vizType="Single render", vizQty=1).total == 99
        rendered = quote("viz", ca, vizType="Single render", vizQty=1).view
        assert all("rush" not in row["label"].lower() for row in rendered["rows"])
        assert all("rush" not in row["sub"].lower() for row in rendered["rows"])

    def test_drafting_fact_grid_splits_the_turnaround(self, ca):
        """BUG 3 — the brief splits savedLine on ' · ' and labels positionally,
        but the drafting turnaround segment ("Standard · 2–5 days") contains that
        separator itself, so it lands as two rows: Turnaround + a stray Detail."""
        q = quote("drafting", ca, service="PDF-to-CAD", sheets=6)
        assert q.view["summary"]["facts"][-2:] == [
            {"k": "Turnaround", "v": "Standard"},
            {"k": "Detail", "v": "2–5 days"},
        ]


@pytest.mark.django_db
class TestBranchEstimateAPI:
    """POST /api/v1/estimates/ — one endpoint, six branches, anonymous allowed."""

    def post(self, api_client, **payload):
        return api_client.post("/api/v1/estimates/", payload, format="json")

    def test_drafting(self, seeded, api_client):
        response = self.post(
            api_client,
            goal="drafting",
            state="CA",
            answers={"service": "PDF-to-CAD", "sheets": 12, "stamp": True, "rush": True},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["goal"] == "drafting"
        assert body["scope"] == "PDF-to-CAD"
        assert float(body["total"]) == 360 + 1500 + 465 == 2325
        assert float(body["low"]) == float(body["high"]) == 2325  # flat, not a band
        assert body["quote"]["headlineTotal"] == "$2,325"
        assert body["quote"]["showJuris"] is False
        assert body["quote"]["summary"]["paras"]

    def test_consult(self, seeded, api_client):
        body = self.post(
            api_client,
            goal="consult",
            state="NY",
            answers={"consultType": "Plan review & markup", "ptype": "Commercial"},
        ).json()
        assert float(body["total"]) == 150
        assert body["project_type"] == "Commercial"
        assert body["quote"]["rows"][0]["sub"] == "Commercial · New York"

    def test_viz(self, seeded, api_client):
        body = self.post(
            api_client,
            goal="viz",
            state="TX",
            answers={"vizType": "Walkthrough", "vizSecs": 45},
        ).json()
        assert float(body["total"]) == 2250
        assert body["quote"]["cta"] == "See my 3D artist →"

    def test_scan(self, seeded, api_client):
        body = self.post(
            api_client,
            goal="scan",
            state="WA",
            answers={"scanType": "Scan-to-BIM", "scanArea": 12000},
        ).json()
        assert float(body["total"]) == 6000
        assert body["sqft"] == 12000
        assert body["quote"]["savedLine"] == "Scan-to-BIM · 12,000 sf · Washington"

    def test_engineering(self, seeded, api_client):
        body = self.post(
            api_client,
            goal="engineering",
            state="CA",
            answers={"engType": "Code consulting", "engHours": 12},
        ).json()
        assert float(body["total"]) == 1800
        assert body["quote"]["match"]["tag"] == "CODE"

    def test_design_keeps_the_original_flat_contract(self, seeded, api_client):
        body = self.post(
            api_client,
            state="CA",
            project_type="Residential",
            scope="Addition",
            sqft=2400,
            timeline="Standard (10–12 wks)",
            addons=["structural", "viz"],
            answers={"beds": "4", "style": "Craftsman"},
        ).json()
        assert body["goal"] == "design"
        assert body["quote"]["headlineTotal"] == "$20,849 – $24,475"
        assert body["quote"]["juris"]["score"] == 82
        assert body["answers"]["beds"] == "4"

    def test_design_still_requires_its_price_inputs(self, seeded, api_client):
        response = self.post(api_client, goal="design", state="CA")
        assert response.status_code == 400
        assert set(response.json()) == {"project_type", "scope", "sqft", "timeline"}

    def test_unknown_branch_answer_is_rejected(self, seeded, api_client):
        response = self.post(
            api_client, goal="drafting", state="CA", answers={"service": "Interpretive dance"}
        )
        assert response.status_code == 400
        assert "service" in response.json()["answers"]

    def test_renovation_areas_reach_the_brief(self, seeded, api_client):
        body = self.post(
            api_client,
            state="CA",
            project_type="Residential",
            scope="Renovation",
            sqft=900,
            timeline="Standard (10–12 wks)",
            answers={"rooms": {"kitchen": True, "primaryBath": True, "garage": False}},
        ).json()
        assert body["quote"]["summary"]["paras"][1].startswith(
            "The remodel covers 2 areas of the home."
        )

    def test_unknown_room_key_is_rejected(self, seeded, api_client):
        response = self.post(
            api_client,
            state="CA",
            project_type="Residential",
            scope="Renovation",
            sqft=900,
            timeline="Standard (10–12 wks)",
            answers={"rooms": {"moat": True}},
        )
        assert response.status_code == 400
        assert "moat" in str(response.json()["answers"]["rooms"])

    def test_unknown_goal_is_rejected(self, seeded, api_client):
        assert self.post(api_client, goal="astrology", state="CA").status_code == 400

    def test_snapshot_is_shareable_and_claimable(self, seeded, api_client, auth_client):
        created = self.post(
            api_client,
            goal="scan",
            state="CA",
            answers={"scanType": "3D laser scanning", "scanArea": 8000},
        ).json()

        detail = api_client.get(f"/api/v1/estimates/{created['id']}/")
        assert detail.status_code == 200
        assert detail.json()["quote"]["total"] == "$1,600"

        claimed = auth_client.post(
            "/api/v1/projects/", {"estimate_id": created["id"]}, format="json"
        )
        assert claimed.status_code == 201
        assert claimed.json()["estimate"]["goal"] == "scan"
        assert claimed.json()["title"] == "3D laser scanning · California"
