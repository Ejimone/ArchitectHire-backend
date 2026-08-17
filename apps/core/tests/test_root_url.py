"""The deployment URL's front door.

This server only ever had routes under `/admin/` and `/api/`, so opening the bare
deployment host — the thing the owner actually types — answered with Django's unstyled
"Not Found" page. That is the wrong first impression of a working system, and the only
person who visits the bare API host wants the admin.
"""

import pytest


@pytest.mark.django_db
def test_the_root_redirects_to_the_admin(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"] == "/admin/"


@pytest.mark.django_db
def test_the_redirect_is_temporary(client):
    """301 is cached by browsers effectively forever. If the root is ever given a real
    page, everyone who visited it beforehand would keep being bounced to /admin/ with no
    way to clear it but their own cache."""
    assert client.get("/").status_code == 302  # not 301


@pytest.mark.django_db
def test_it_lands_on_a_real_admin_page(client):
    """Signed out, that means the login screen rather than another 404."""
    response = client.get("/", follow=True)
    assert response.status_code == 200
    assert response.redirect_chain[-1][0].startswith("/admin/login/")


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/nope", "/api/v1/bogus/", "/adminx/"])
def test_unknown_paths_still_404(client, path):
    """Only the root is redirected. An API that bounced every typo to the admin would
    hide genuine routing mistakes from the clients making them."""
    assert client.get(path).status_code == 404
