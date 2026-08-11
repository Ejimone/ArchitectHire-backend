"""Stage 11 guards: query counts on hot endpoints and a valid OpenAPI schema."""

import pytest
from django.core.management import call_command


@pytest.fixture(scope="module")
def seeded(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("seed", "--all")


@pytest.mark.django_db
def test_composed_page_query_budget(seeded, api_client, django_assert_max_num_queries):
    # Warm the content-version key, then the composed page must stay within budget
    # (one query per block type + seo + settings + copy + media — no N+1s).
    api_client.get("/api/v1/content/pages/landing/")
    from apps.core.cache import bump_content_version

    bump_content_version()  # force a rebuild so we measure the uncached path
    with django_assert_max_num_queries(20):
        response = api_client.get("/api/v1/content/pages/landing/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_cached_page_hits_no_content_queries(seeded, api_client, django_assert_max_num_queries):
    api_client.get("/api/v1/content/pages/landing/")  # prime
    with django_assert_max_num_queries(3):  # cache lookups only, no content queries
        assert api_client.get("/api/v1/content/pages/landing/").status_code == 200


@pytest.mark.django_db
def test_openapi_schema_generates(api_client):
    response = api_client.get("/api/schema/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "openapi" in content
    for path in ("/api/v1/estimates/", "/api/v1/content/pages/", "/api/v1/orders/quote/"):
        assert path in content
