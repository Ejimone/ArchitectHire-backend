"""Jurisdiction model strings and the city/state content endpoints."""

import pytest
from django.core.management import call_command

from apps.jurisdictions.models import City, State


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--domain", "jurisdictions")


def test_state_str_includes_score():
    assert str(State(name="California", complexity_score=82)) == "California (82)"


def test_city_str_includes_state_code():
    assert str(City(name="Oakland", state=State(code="CA"))) == "Oakland, CA"


@pytest.mark.django_db
class TestJurisdictionEndpoints:
    def test_state_detail(self, seeded, api_client):
        body = api_client.get("/api/v1/jurisdictions/states/ca/").json()
        assert body["code"] == "CA"
        assert body["band"] == "HIGH"

    def test_unknown_state_404(self, seeded, api_client):
        assert api_client.get("/api/v1/jurisdictions/states/zz/").status_code == 404

    def test_cities_list(self, seeded, api_client):
        body = api_client.get("/api/v1/jurisdictions/cities/").json()
        assert any(c["slug"] == "oakland" for c in body["cities"])

    def test_city_detail(self, seeded, api_client):
        body = api_client.get("/api/v1/jurisdictions/cities/oakland/").json()
        assert body["name"] == "Oakland"
        assert body["state"] == "CA"

    def test_unknown_city_404(self, seeded, api_client):
        assert api_client.get("/api/v1/jurisdictions/cities/not-a-city/").status_code == 404
