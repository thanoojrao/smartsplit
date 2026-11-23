"""Giving receipt lines their item keys (SPEC section 6.4).

Three steps so the model call happens outside any transaction (SPEC section 12.2): read this
place's aliases and the known keys, match (asking the model only for names nothing else
matched), then remember new matches when the draft is written.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import MatchHow
from smartsplit.domain.model import ItemAlias, LineItem
from smartsplit.domain.values import LocalScope
from smartsplit.engine import Match, discount_links, match_item
from smartsplit.ports.llm import Canonicalizer
from smartsplit.ports.repository import UnitOfWork


@dataclass(frozen=True, slots=True)
class MatchInputs:
    """What matching needs from the database, read up front so no transaction stays open."""

    scope: LocalScope
    aliases: Mapping[str, str]
    """Normalized raw name → item key, remembered in this scope."""
    known_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class MatchedLines:
    """Matched lines plus what to remember and count once the draft is written."""

    lines: tuple[LineItem, ...]
    new_aliases: tuple[ItemAlias, ...]
    """Fuzzy and model matches to remember in the scope; each is shown once in the summary."""
    model_calls: int
    """How many times the model was asked, for the per-person daily limit (SPEC 12.2)."""


def load_match_inputs(uow: UnitOfWork, scope: LocalScope) -> MatchInputs:
    """Read this place's aliases and the known keys in a short transaction."""
    aliases = {alias.raw_name: alias.item_key for alias in uow.aliases.for_scope(scope)}
    return MatchInputs(scope, aliases, uow.items.keys())


def match_lines(
    lines: Sequence[LineItem],
    inputs: MatchInputs,
    canonicalizer: Canonicalizer,
    threshold: int,
) -> MatchedLines:
    """Set `canonical`, `match_how` and `match_is_new` on every line.

    A linked discount takes its line's key, so it is shared like it; it is never sent to the
    model or remembered on its own. Every other line, refunds included, is matched by name.
    Keys the model creates count as known for the rest of the receipt, so "Dragon Fruit" and
    "Dragon Fruits" cost one model call. LlmUnavailableError propagates.
    """
    links = discount_links(lines)
    by_id = {line.id: line for line in lines}
    known = set(inputs.known_keys)
    by_name: dict[str, tuple[Match, bool]] = {}
    matched: dict[str, LineItem] = {}
    calls = 0
    for line in lines:
        if line.id in links:
            continue
        name = normalize_item_name(line.name)
        if name not in by_name:
            match, is_new, asked = _match_name(line.name, inputs, known, canonicalizer, threshold)
            by_name[name] = (match, is_new)
            calls += asked
            if match.item_key is not None:
                known.add(match.item_key)
        match, is_new = by_name[name]
        matched[line.id] = replace(
            line, canonical=match.item_key, match_how=match.how, match_is_new=is_new
        )
    for line_id, parent_id in links.items():
        parent = matched[parent_id]
        matched[line_id] = replace(
            by_id[line_id],
            canonical=parent.canonical,
            match_how=parent.match_how,
            match_is_new=False,
        )
    new_aliases = tuple(
        ItemAlias(inputs.scope, name, match.item_key)
        for name, (match, is_new) in by_name.items()
        if is_new and match.item_key is not None
    )
    return MatchedLines(tuple(matched[line.id] for line in lines), new_aliases, calls)


def _match_name(
    raw_name: str,
    inputs: MatchInputs,
    known: set[str],
    canonicalizer: Canonicalizer,
    threshold: int,
) -> tuple[Match, bool, int]:
    """The match, whether it is new here (remembered and shown once), and model calls made."""
    match = match_item(raw_name, inputs.aliases, known, threshold)
    if match.how is MatchHow.FUZZY:
        return match, True, 0
    if match.how is not MatchHow.NONE:
        return match, False, 0
    name = normalize_item_name(raw_name)
    key = normalize_item_name(canonicalizer.canonicalize(raw_name, sorted(known)))
    if not key or key == name:
        return Match(name, MatchHow.LLM), False, 1
    return Match(key, MatchHow.LLM), True, 1


def remember_matches(uow: UnitOfWork, matched: MatchedLines) -> None:
    """Store the new aliases and make every line's key a known item, for later receipts."""
    for alias in matched.new_aliases:
        uow.aliases.put(alias)
    for line in matched.lines:
        if line.canonical is not None:
            uow.items.ensure(line.canonical)
