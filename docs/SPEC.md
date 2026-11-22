# SmartSplit — Specification

SmartSplit is a self-hostable, open-source expense splitter for shared houses.
You snap a receipt, and it splits each line item between the right people, using
what it remembers about who uses what ("don't add milk to Raj", "Sam usually
doesn't eat chips"). It asks when unsure, keeps its own ledger, and will later
talk to people through a WhatsApp bot.

This document is the source of truth. If the code and this spec disagree, the
spec wins, unless DECISIONS.md records a change.

---

## 1. Scope of this build (the first run)

**In scope:** the core engine, end to end, with no WhatsApp:

1. Domain model and Postgres persistence
2. Split engine (pure, deterministic)
3. Preference memory (rules) and item matching
4. Receipt parsing from an image (Claude vision, behind an interface)
5. Natural-language commands → structured actions (Claude, behind an interface)
6. Ledger: balances, debt simplification, settle-up
7. Conversation orchestrator: the bill flow as a channel-agnostic state machine
8. A CLI channel and a FastAPI HTTP API that drive the orchestrator

**Out of scope (do not build):** the WhatsApp/Baileys gateway, the Splitwise
sync adapter, payment links, auth/multi-tenant hosting, and a web UI. Design for
them through the interfaces below, but write no code for them.

---

## 2. Architecture

Layered, with dependencies only pointing downward. `scripts/check.sh` enforces
this with import-linter, so a violation fails the build.

```
smartsplit/
  domain/        pure dataclasses, enums, money helpers. Imports nothing from smartsplit.
  engine/        split engine + rule matching. Pure functions. Imports only domain.
  ledger/        balances + debt simplification. Pure. Imports only domain.
  ports/         Protocol interfaces: ReceiptParser, CommandInterpreter, Repository, Channel, Clock.
  services/      orchestrator + use-cases. Imports domain, engine, ledger, ports. Never adapters.
  adapters/
    db/          SQLAlchemy models, repositories, Alembic migrations (implements ports.Repository)
    llm/         Anthropic-backed ReceiptParser + CommandInterpreter (implements ports)
    fakes/       in-memory/fake implementations of every port, used by tests and the CLI demo
  entrypoints/
    api/         FastAPI app (webhook-style inbound messages + REST reads)
    cli/         Typer CLI channel
  config.py      settings from env (pydantic-settings)
```

Rules:
- `domain`, `engine` and `ledger` are pure: no I/O, no clock, no randomness, no logging side effects.
- Only `adapters/llm` imports `anthropic`. Only `adapters/db` imports `sqlalchemy`.
- `services` depends on ports (Protocols), and gets concrete adapters injected at the entrypoint.
- Wiring happens in one composition root per entrypoint.

## 3. Conventions

- **Money is integer cents** (`int`) everywhere. Never `float`. Use `fractions.Fraction` internally where exact division matters.
- One currency per group (ISO code on the group). No FX.
- IDs are strings (UUID4 hex) generated in services/adapters, never in pure layers.
- Time comes from the `Clock` port.
- Python 3.12+, full type hints, `mypy --strict` clean.
- Files stay under ~300 lines. Functions stay short and single-purpose.

---

## 4. Domain model

| Entity | Key fields |
|---|---|
| `Person` | id, display_name, phone (E.164, optional), aliases (list[str]) |
| `Group` | id, name, currency, member ids (ordered), channel_ref (opaque, e.g. a WhatsApp group id later) |
| `Rule` | id, group_id, member_id, item_key, kind (`exclude` \| `soft_exclude` \| `only`), source (`stated` \| `learned`), created_at |
| `Receipt` | id, group_id, payer_id, merchant, purchased_at, currency, line_items, adjustments_cents, total_cents, image_ref |
| `LineItem` | id, name, amount_cents (may be negative for discount lines), canonical (optional item key) |
| `Expense` | id, group_id, receipt_id (optional), payer_id, description, total_cents, shares {member_id: cents}, created_at |
| `Settlement` | id, group_id, from_id, to_id, amount_cents, created_at |
| `PendingQuestion` | id, group_id, receipt_id, item_id, member_id (optional), reason, status |

`adjustments_cents` = tax + tip + service charges − receipt-level discounts.
Invariant: `sum(line_items.amount_cents) + adjustments_cents == total_cents`.
The parser must flag a receipt where this doesn't hold, not silently fix it.

---

## 5. Split engine contract (FROZEN)

`smartsplit.engine.split_receipt(...)`. The signature and types live in
`src/smartsplit/engine/__init__.py`. `tests/acceptance/test_split_engine.py`
pins the behavior and **must not be modified**.

Semantics, in order, for each line item:

1. **Item key** = `item.canonical` if set, else `normalize(item.name)`.
   `normalize` = lowercase, trim, collapse internal whitespace.
2. **Override** for this item id (from the user's answers) → those members, in group order. No questions.
3. Else, if any `only` rules match the key → exactly those members.
4. Else, start with all members, remove members with an `exclude` rule for the key.
   A `soft_exclude` keeps the member and emits `Question(item_id, member_id, SOFT_RULE)`.
5. If the result is empty → assign to all members and emit `Question(item_id, None, NO_ELIGIBLE_MEMBERS)`.

Then compute amounts:
- Each item is split equally among its assignees (exact `Fraction`s).
- `adjustments_cents` is allocated to members in proportion to their item subtotals. If the subtotals sum to 0 (for example no items, or a discount cancelling everything out), split it equally.
- **Rounding:** floor each member's exact share, then hand the leftover cents one at a time to the members with the largest fractional remainders. Break ties by member order.
- Result: `shares` has every member (0 allowed) and sums **exactly** to `sum(items) + adjustments_cents`.

Validation: an empty or duplicate member list, or an override naming a non-member, raises `ValueError`.

---

## 6. Preference memory & matching

- Rules are stored per group and per member, keyed by item key.
- **Canonicalization:** receipt names are messy (`"2% MLK GAL"`). A `canonicalize(name, known_keys)` step maps a raw name to an existing item key or proposes a new one:
  1. exact match on normalized name or a stored alias
  2. deterministic fuzzy match (token overlap / rapidfuzz ratio ≥ threshold, set in config)
  3. otherwise ask the LLM `CommandInterpreter.canonicalize` (behind the port, cached per group in the DB)
- **Learning:** when the user answers a question the same way twice for the same (member, item key), with no contradicting answer, create a `learned` rule (`exclude` or `only`). Stated rules always beat learned ones. A new stated rule replaces any rule for the same (member, key).
- Users can list, add and delete rules in natural language ("what do you know about Raj?", "Raj drinks milk now").

## 7. Receipt parsing

- Port: `ReceiptParser.parse(image_bytes, mime_type, hint_currency) -> ParsedReceipt`.
- Anthropic adapter: one vision call with a strict JSON schema (use tool-use / structured output), model from config. Retries once on invalid JSON. Returns line items in integer cents, plus adjustments, total and a `confidence` per item.
- If the invariant in §4 fails, `ParsedReceipt.warnings` says so, and the orchestrator asks the user to confirm the total.
- Tests use recorded fixtures (`tests/fixtures/receipts/*.json`). No network in tests. One opt-in live test runs only when `SMARTSPLIT_LIVE_LLM=1`.

## 8. Natural-language commands

Port: `CommandInterpreter.interpret(text, context) -> Command`, where `Command` is a tagged union, for example:
`AddRule`, `DeleteRule`, `ListRules`, `AnswerQuestion`, `ConfirmSplit`, `EditSplit`,
`ShowBalances`, `SettleUp`, `AddManualExpense`, `Help`, `Unknown`.
The Anthropic adapter uses tool-use, with one tool per command. The fake adapter uses
simple keyword/regex patterns, good enough for tests and the CLI demo.

## 9. Ledger

- Balance per member = paid − owed, across expenses and settlements. Always sums to 0 per group.
- `simplify_debts(balances) -> list[Transfer]` gives the minimal-count greedy settlement (largest creditor ↔ largest debtor). It's deterministic, with ties broken by member order.
- Settling up records a `Settlement`. Expenses and settlements are append-only. Corrections are new reversing entries, never edits.

## 10. Orchestrator (bill flow)

A channel-agnostic state machine in `services/`:

```
image received → parse → canonicalize items → split_receipt
  → no questions: send proposed split, wait for confirm / edit
  → questions: ask them one message at a time (batch if ≤3), collect answers as overrides
  → re-split → confirm → write Expense → learn from answers → reply with new balances
```

- Inbound: `InboundMessage(channel, conversation_ref, sender_ref, text | image)`.
- Outbound: `OutboundMessage(conversation_ref, text)`. Plain text that reads well in a chat app: short lines, no markdown tables.
- State lives in the DB, so a restart mid-flow resumes cleanly.
- Every state transition is covered by an integration test using fakes.

## 11. Entrypoints

- **CLI** (`smartsplit`): `group create`, `member add`, `receipt add <image> --payer`, `say "<text>"`, `balances`, `rules`. Use it to demo the full flow with the fake or the real LLM adapters (`--live`).
- **API** (FastAPI): `POST /v1/messages` (an `InboundMessage` JSON → list of `OutboundMessage`), `GET /v1/groups/{id}/balances`, `GET /v1/groups/{id}/rules`, `GET /healthz`. This is the endpoint the future WhatsApp gateway will call.

## 12. Future (design for it, don't build it)

- The WhatsApp gateway is a separate small Node service using Baileys. It turns WhatsApp events into `POST /v1/messages` and sends the replies. The bot runs on a dedicated number, never a personal one.
- A Splitwise sync adapter would mirror confirmed `Expense`s out.
- Payment links: UPI and Venmo deep links in balance replies.
