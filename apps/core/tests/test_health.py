import pytest

from apps.core import views as core_views


class _BrokenConnection:
    def cursor(self):
        raise RuntimeError("database is down")


class _BrokenCache:
    def set(self, *args, **kwargs):
        raise RuntimeError("redis is down")


@pytest.mark.django_db
def test_health_returns_ok(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["cache"] is True


@pytest.mark.django_db
def test_health_reports_degraded_when_the_database_is_unreachable(client, monkeypatch):
    monkeypatch.setattr(core_views, "connection", _BrokenConnection())
    response = client.get("/api/health/")
    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "degraded", "db": False, "cache": True}


@pytest.mark.django_db
def test_health_reports_degraded_when_the_cache_is_unreachable(client, monkeypatch):
    monkeypatch.setattr(core_views, "cache", _BrokenCache())
    response = client.get("/api/health/")
    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "degraded", "db": True, "cache": False}
