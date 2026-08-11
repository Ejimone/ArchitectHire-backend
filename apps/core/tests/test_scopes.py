import pytest
from django.core.exceptions import ValidationError

from apps.core.scopes import (
    STATIC_PAGE_KEYS,
    is_valid_scope,
    static_scope_choices,
    validate_scope,
)


@pytest.mark.parametrize(
    "scope",
    [
        "landing",
        "services",
        "for-experts",
        "expert-pricing",
        "professional-tools",
        "account",
        "matches",
        "engagement",
        "pro",
        "project-type:adu",
        "city:oakland",
        "state:CA",
        "state:DC",
        "state:PR",
    ],
)
def test_valid_scopes(scope):
    assert is_valid_scope(scope)


@pytest.mark.parametrize(
    "scope", ["", "unknown-page", "state:XYZ", "state:ca", "project-type:", "bogus:thing"]
)
def test_invalid_scopes(scope):
    assert not is_valid_scope(scope)
    with pytest.raises(ValidationError):
        validate_scope(scope)


def test_static_scope_choices_mirror_the_registry():
    assert static_scope_choices() == [(key, key) for key in STATIC_PAGE_KEYS]
