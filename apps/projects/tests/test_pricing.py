"""Exact-value tests for the estimate engine.

Pinned values derive from the design's own defaults (Get Started prototype:
2,400 sf · California · structural + viz): rate $5.31/sf → base $12,750,
add-ons $4,200, multiplier 1.337 → total = $22,662.15.
"""

import math

import pytest
from django.core.management import call_command

from apps.jurisdictions.models import State
from apps.projects.pricing import compute_estimate


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--all")


@pytest.mark.django_db
class TestEstimateEngine:
    def test_design_default_case_california(self, seeded):
        ca = State.objects.get(code="CA")
        assert ca.complexity_score == 82
        result = compute_estimate(sqft=2400, state=ca, addon_keys=["structural", "viz"])
        assert result.base == 12750
        assert result.addon_total == 4200
        assert result.multiplier == pytest.approx(1.337)
        assert result.total == pytest.approx(22662.15, abs=0.01)
        assert result.low == pytest.approx(22662.15 * 0.92, abs=0.01)
        assert result.high == pytest.approx(22662.15 * 1.08, abs=0.01)

    def test_low_complexity_north_dakota(self, seeded):
        nd = State.objects.get(code="ND")
        assert nd.complexity_score == 37
        result = compute_estimate(sqft=2400, state=nd, addon_keys=[])
        assert result.multiplier == pytest.approx(1.1795)
        assert result.total == pytest.approx(12750 * 1.1795, abs=0.01)

    def test_rate_curve_endpoints(self, seeded):
        ca = State.objects.get(code="CA")
        small = compute_estimate(sqft=200, state=ca, addon_keys=[])
        large = compute_estimate(sqft=8000, state=ca, addon_keys=[])
        # Declining $/sf curve: $8.50/sf at 200 sf → $3.46/sf at 8,000 sf
        assert small.rate == pytest.approx(3.2 + 5.3 * math.exp(-200 / 2600), abs=1e-9)
        assert small.rate == pytest.approx(8.11, abs=0.01)
        assert large.rate == pytest.approx(3.44, abs=0.01)
        assert large.base > small.base  # total base still grows with size

    def test_base_rounds_to_50(self, seeded):
        ca = State.objects.get(code="CA")
        for sqft in (700, 1300, 3350, 5150):
            result = compute_estimate(sqft=sqft, state=ca, addon_keys=[])
            assert result.base % 50 == 0

    def test_all_addons(self, seeded):
        ca = State.objects.get(code="CA")
        result = compute_estimate(
            sqft=2400, state=ca, addon_keys=["structural", "mep", "viz", "energy"]
        )
        assert result.addon_total == 2400 + 3200 + 1800 + 1200

    def test_jurisdiction_factors_shape(self, seeded):
        ca = State.objects.get(code="CA")
        factors = ca.factors
        assert [f["name"] for f in factors] == [
            "Seismic zone",
            "Historic overlay",
            "Climate load",
            "Coastal / flood",
            "Drawing set",
        ]
        drawing_set = factors[-1]
        assert drawing_set["level"] in ("STANDARD", "EXTENSIVE")


@pytest.mark.django_db
class TestEstimateAPI:
    def test_create_estimate_anonymous(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/estimates/",
            {
                "project_type": "Residential",
                "scope": "Addition",
                "sqft": 2400,
                "state": "CA",
                "timeline": "Standard (10–12 wks)",
                "addons": ["structural", "viz"],
            },
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert float(body["base"]) == 12750
        assert float(body["total"]) == pytest.approx(22662.15, abs=0.01)
        assert body["jurisdiction"]["score"] == 82
        assert body["jurisdiction"]["band"] == "High complexity"
        assert len(body["jurisdiction"]["factors"]) == 5

        # Shareable snapshot
        detail = api_client.get(f"/api/v1/estimates/{body['id']}/")
        assert detail.status_code == 200
        assert detail.json()["total"] == body["total"]

    def test_invalid_scope_for_type(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/estimates/",
            {
                "project_type": "Commercial",
                "scope": "ADU",
                "sqft": 1000,
                "state": "CA",
                "timeline": "Standard (10–12 wks)",
                "addons": [],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_unknown_state(self, seeded, api_client):
        response = api_client.post(
            "/api/v1/estimates/",
            {
                "project_type": "Residential",
                "scope": "ADU",
                "sqft": 1000,
                "state": "ZZ",
                "timeline": "Standard (10–12 wks)",
                "addons": [],
            },
            format="json",
        )
        assert response.status_code == 400
