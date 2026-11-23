# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

M1 is done. **Continue with M2**, then M3, then stop at CHECKPOINT A (no stop between M2 and M3).

M2 = everything in CONTRACTS §1 in `smartsplit.domain` (`enums.py`, `values.py`, `model.py`,
`messages.py`, `commands.py`, `prompts.py`, plus a `phone.py` E.164 helper using `phonenumbers`);
the ports from CONTRACTS §4 in `smartsplit.ports` (Clock, IdGenerator, ImageStore, ReceiptParser,
CommandInterpreter, Repository with a unit of work and one store per aggregate, the port errors);
`src/smartsplit/config.py` (pydantic-settings, SPEC §12.1); the Postgres adapter in `adapters/db`
(SQLAlchemy Core tables, Alembic migration, advisory lock per conversation); a filesystem ImageStore
in `adapters/files` (add it to the "Adapters are independent" import-linter contract); in-memory
fakes in `adapters/fakes`; and repository tests run against real Postgres (`db` marker,
`TEST_DATABASE_URL`, fail-not-skip). Review range for M2: `42c46b6..HEAD`.

## Milestones

- [x] M0 — Scaffold: spec, tooling, quality gate, frozen engine contract + acceptance tests
- [x] M1 — Split engine (SPEC §5): `split_receipt` incl. weighted overrides, `fold_item_tax` (§5.1), `amounts_to_weights` (§5.2); all acceptance tests pass + own unit tests (negative subtotals, many members, large amounts, weights, exact amounts, validation)
- [ ] M2 — Domain model, messages and commands (CONTRACTS §1) + ports incl. ImageStore with unit of work (CONTRACTS §4) + `config.py` + Postgres adapter with Alembic migration + filesystem ImageStore (add `adapters.files` to the independence contract) + repository tests against real Postgres
- [ ] M3 — Rules and matching (SPEC §6): scopes, `resolve_rules`, item matching with per-scope aliases and discount linking, learning, with a fake LLM canonicalizer

**CHECKPOINT A** — stop, push, notify the user, and summarize. The core logic is reviewed by the human before anything is built on top of it.

- [ ] M4 — Ledger (SPEC §9): context balances incl. settlements, group `simplify_debts`, personal pairs, overall view, payment allocation, square-up
- [ ] M5 — Receipt parsing (SPEC §7): port + Anthropic adapter + fixtures + opt-in live test; quantity, taxed, discount_for, confidence, validation
- [ ] M6 — Command interpreter (SPEC §8): full command set, Anthropic adapter (tool use) + keyword fake
- [ ] M7 — Orchestrator I (SPEC §10.1–10.4, 10.7, §12.2–12.3): reacting rules, identity + onboarding + membership, group and personal bill flows, prompts, review edits, confirm, cancel, queue, duplicates, privacy routing, balances queries; idempotency + serialization; DB-backed state; integration tests with fakes (no notifications yet)
- [ ] M8 — Orchestrator II (SPEC §10.5–10.8): notifications outbox + `tick` (reminders, expiry, batching), invites, saved-bill edits/deletes/"not mine", payments (record, not received, undo, overpay, square-up), reminders, history, stop/start, caps
- [ ] M9 — CLI + FastAPI entrypoints (SPEC §11) incl. API token, README "try it" walkthrough with the fake adapters

**CHECKPOINT B** — final: stop, push, open a PR, notify the user, and summarize.

## Log

- M0: scaffold created by hand. Engine contract frozen in `src/smartsplit/engine/__init__.py`. Commit `fc41671`.
- M1: `split_receipt` (weighted overrides, clamped adjustments, one floor + largest-remainder helper), `fold_item_tax`, `amounts_to_weights`; frozen types moved to `engine/split.py` and re-exported; CI actions on Node 24; 74 tests, 100% coverage; review: no must-fix. Commit `42c46b6`.

## Follow-ups

(non-blocking review findings go here)

- (M1 review) `amounts_to_weights` raises on no fixed amounts: the orchestrator (M7) must use a plain list override for an equal split, never route "no exact amounts" here.
