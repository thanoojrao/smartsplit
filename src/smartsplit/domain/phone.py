"""Phone numbers: a person's identity, stored in E.164 (SPEC sections 3 and 6.1)."""

import phonenumbers


def normalize_phone(raw: str, default_region: str) -> str:
    """Return `raw` in E.164, reading numbers without a country code in `default_region`.

    Raises ValueError for anything that isn't a valid number, so the bot can ask again.
    """
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException as error:
        raise ValueError(f"not a phone number: {error}") from error
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("not a valid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(e164: str) -> str:
    """Show only the country code and last five digits, as bot text never shows full numbers."""
    parsed = phonenumbers.parse(e164, None)
    country = f"+{parsed.country_code}"
    digits = e164.removeprefix(country)
    visible = digits[-5:]
    return f"{country}{'•' * (len(digits) - len(visible))}{visible}"
