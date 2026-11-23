"""Phone numbers (SPEC sections 3 and 6.1)."""

import pytest

from smartsplit.domain.phone import mask_phone, normalize_phone


@pytest.mark.parametrize(
    "raw", ["098765 43210", "+91 98765-43210", "9876543210", "+919876543210", "0091 98765 43210"]
)
def test_formats_of_one_number_normalize_to_the_same_e164(raw: str) -> None:
    # A8
    assert normalize_phone(raw, "IN") == "+919876543210"


def test_the_default_region_applies_only_without_a_country_code() -> None:
    assert normalize_phone("(415) 555-2671", "US") == "+14155552671"
    assert normalize_phone("+44 20 7946 0958", "IN") == "+442079460958"


@pytest.mark.parametrize("raw", ["", "hello", "123", "+91 12"])
def test_invalid_numbers_raise(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw, "IN")


def test_masking_keeps_country_code_and_last_five() -> None:
    assert mask_phone("+919876543210") == "+91•••••43210"
    assert mask_phone("+14155552671") == "+1•••••52671"
