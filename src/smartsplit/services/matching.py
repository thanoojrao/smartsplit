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
from smartsplit.engine import Match, match_item
from smartsplit.ports.llm import Canonicalizer
from smartsplit.ports.repository import UnitOfWork


@dataclass(frozen=True, slots=True)
class MatchInputs:
    scope: LocalScope
    aliases: Mapping[str, str]
    """Normalized raw name → item key, remembered in this scope."""
    known_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class MatchedLines:
    lines: tuple[LineItem, ...]
    new_aliases: tuple[ItemAlias, ...]
    """Fuzzy and model matches to remember in the scope; each is shown once in the summary."""


def load_match_inputs(uow: UnitOfWork, scope: LocalScope) -> MatchInputs:
    aliases = {alias.raw_name: alias.item_key for alias in uow.aliases.for_scope(scope)}
    return MatchInputs(scope, aliases, uow.items.keys())


def match_lines(
    lines: Sequence[LineItem],
    inputs: MatchInputs,
    canonicalizer: Canonicalizer,
    threshold: int,
) -> MatchedLines:
    """Set `canonical`, `match_how` and `match_is_new` on every line.

    A discount linked to another line takes that line's key, so it is shared like it; it is
    never sent to the model or remembered on its own. The model is asked at most once per
    distinct name.
    """
    by_name: dict[str, tuple[Match, bool]] = {}
    matched: dict[str, LineItem] = {}
    parents = _link_parents(lines)
    by_id = {line.id: line for line in lines}
    for line in lines:
        if line.id in parents:
            continue
        name = normalize_item_name(line.name)
        if name not in by_name:
            by_name[name] = _match_name(line.name, inputs, canonicalizer, threshold)
        match, is_new = by_name[name]
        matched[line.id] = replace(
            line, canonical=match.item_key, match_how=match.how, match_is_new=is_new
        )
    for line_id, parent_id in parents.items():
        line, parent = by_id[line_id], matched[parent_id]
        matched[line_id] = replace(
            line, canonical=parent.canonical, match_how=parent.match_how, match_is_new=False
        )
    new_aliases = tuple(
        ItemAlias(inputs.scope, name, match.item_key)
        for name, (match, is_new) in by_name.items()
        if is_new and match.item_key is not None
    )
    return MatchedLines(tuple(matched[line.id] for line in lines), new_aliases)


def _link_parents(lines: Sequence[LineItem]) -> dict[str, str]:
    """Discount line id → the plain line it reduces. Links to unknown or discount lines don't
    count, so such a line is matched on its own name."""
    by_id = {line.id: line for line in lines}
    return {
        line.id: line.discount_for
        for line in lines
        if line.discount_for in by_id and by_id[line.discount_for].discount_for is None
    }


def _match_name(
    raw_name: str, inputs: MatchInputs, canonicalizer: Canonicalizer, threshold: int
) -> tuple[Match, bool]:
    """The match and whether it is new here (to be remembered and shown once)."""
    match = match_item(raw_name, inputs.aliases, inputs.known_keys, threshold)
    if match.how is MatchHow.FUZZY:
        return match, True
    if match.how is not MatchHow.NONE:
        return match, False
    name = normalize_item_name(raw_name)
    key = normalize_item_name(canonicalizer.canonicalize(raw_name, sorted(inputs.known_keys)))
    if not key or key == name:
        return Match(name, MatchHow.LLM), False
    return Match(key, MatchHow.LLM), True


def remember_matches(uow: UnitOfWork, matched: MatchedLines) -> None:
    """Store the new aliases and make every line's key a known item, for later receipts."""
    for alias in matched.new_aliases:
        uow.aliases.put(alias)
    for line in matched.lines:
        if line.canonical is not None:
            uow.items.ensure(line.canonical)
