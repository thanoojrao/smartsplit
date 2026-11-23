"""Matching messy receipt names to item keys, deterministically (SPEC section 6.4).

The model is only asked when this returns `MatchHow.NONE`; that call lives in services.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from rapidfuzz import fuzz

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import MatchHow


@dataclass(frozen=True, slots=True)
class Match:
    """An item key and how it was found; `item_key` is None only with `MatchHow.NONE`."""

    item_key: str | None
    how: MatchHow


def match_item(
    raw_name: str, aliases: Mapping[str, str], known_keys: Collection[str], threshold: int
) -> Match:
    """Find the item key for one receipt name, from the cheapest, surest source down.

    `aliases` are this place's remembered matches (normalized raw name → key). An alias is
    checked before an exact key match, because it records what people here said ("that's not
    milk"). Fuzzy matching takes the best rapidfuzz ratio at or above `threshold`, ties broken
    by key order, so results don't depend on set iteration order.
    """
    name = normalize_item_name(raw_name)
    if name in aliases:
        return Match(aliases[name], MatchHow.ALIAS)
    if name in known_keys:
        return Match(name, MatchHow.EXACT)
    scored = [(fuzz.ratio(name, key), key) for key in sorted(known_keys)]
    best_score, best_key = max(scored, key=lambda pair: pair[0], default=(0.0, None))
    if best_key is not None and best_score >= threshold:
        return Match(best_key, MatchHow.FUZZY)
    return Match(None, MatchHow.NONE)
