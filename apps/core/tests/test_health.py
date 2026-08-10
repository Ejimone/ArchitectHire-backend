import pytest


@pytest.mark.django_db
def test_health_returns_ok(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["cache"] is True
