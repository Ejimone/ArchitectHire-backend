import pytest
from django.core.exceptions import ValidationError

from apps.core.scopes import is_valid_scope, validate_scope


@pytest.mark.parametrize(
    "scope",
    [
        "landing",
        "services",
        "for-experts",
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
