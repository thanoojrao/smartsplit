"""Cleaning the model's words before they are sent (SPEC 8.5): handles become names, markdown
becomes plain chat text (WhatsApp's *bold* at most), and anything that looks like a phone
number is masked."""

import re

from smartsplit.domain.phone import mask_phone, normalize_phone
from smartsplit.services.handles import HANDLE, Handles

_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-+]\s+", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_CODE = re.compile(r"`+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
MIN_INTERNATIONAL_DIGITS = 8
MIN_LOCAL_DIGITS = 10
"""Without a "+", fewer digits are more likely a date or an amount than a number."""


def clean_reply(text: str, handles: Handles) -> str:
    """The model's text, safe and plain for a group chat."""
    cleaned = HANDLE.sub(lambda m: handles.label(m.group(0)) or m.group(0), text)
    cleaned = _BOLD.sub(lambda m: f"*{m.group(1) or m.group(2)}*", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _BULLET.sub(r"\1• ", cleaned)
    cleaned = _LINK.sub(r"\1 (\2)", cleaned)
    cleaned = _CODE.sub("", cleaned)
    cleaned = _PHONE.sub(_mask, cleaned)
    return cleaned.strip()


def _mask(match: re.Match[str]) -> str:
    """Only the last five digits stay, as everywhere bot text shows a number (SPEC 6.1)."""
    digits = "".join(ch for ch in match.group(0) if ch.isdigit())
    plus = "+" if match.group(0).startswith("+") else ""
    if len(digits) < (MIN_INTERNATIONAL_DIGITS if plus else MIN_LOCAL_DIGITS):
        return match.group(0)
    if plus:
        try:
            return mask_phone(normalize_phone(f"+{digits}", "ZZ"))
        except ValueError:
            pass
    return f"{plus}{'•' * (len(digits) - 5)}{digits[-5:]}"
