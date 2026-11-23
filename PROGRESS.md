# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

M1–M4 done. **Continue with M6** (command interpreter, SPEC §8), then M7 → M9 without stopping
(user-confirmed), same process per milestone; stop at CHECKPOINT B (push, open the PR, notify,
summarize). M6 review range: starts at the M5 close-out commit below. No Anthropic API key here: the live test is skipped
unless SMARTSPLIT_LIVE_LLM=1; tests use the recorded-shape fixtures in `tests/fixtures/receipts/`.
One question is open for the user (DECISIONS "Open": square-up when a greedy plan reshuffles);
option (a) is built, nothing is blocked by it.

## Milestones

- [x] M0 — Scaffold: spec, tooling, quality gate, frozen engine contract + acceptance tests
- [x] M1 — Split engine (SPEC §5): `split_receipt` incl. weighted overrides, `fold_item_tax` (§5.1), `amounts_to_weights` (§5.2); all acceptance tests pass + own unit tests (negative subtotals, many members, large amounts, weights, exact amounts, validation)
- [x] M2 — Domain model, messages and commands (CONTRACTS §1) + ports incl. ImageStore with unit of work (CONTRACTS §4) + `config.py` + Postgres adapter with Alembic migration + filesystem ImageStore (add `adapters.files` to the independence contract) + repository tests against real Postgres
- [x] M3 — Rules and matching (SPEC §6): scopes, `resolve_rules`, item matching with per-scope aliases and discount linking, learning, with a fake LLM canonicalizer

**CHECKPOINT A** — stop, push, notify the user, and summarize. The core logic is reviewed by the human before anything is built on top of it.

- [x] M4 — Ledger (SPEC §9): context balances incl. settlements, group `simplify_debts`, personal pairs, overall view, payment allocation, square-up
- [x] M5 — Receipt parsing (SPEC §7): port + Anthropic adapter + fixtures + opt-in live test; quantity, taxed, discount_for, confidence, validation
- [ ] M6 — Command interpreter (SPEC §8): full command set, Anthropic adapter (tool use) + keyword fake
- [ ] M7 — Orchestrator I (SPEC §10.1–10.4, 10.7, §12.2–12.3): reacting rules, identity + onboarding + membership, group and personal bill flows, prompts, review edits, confirm, cancel, queue, duplicates, privacy routing, balances queries; idempotency + serialization; DB-backed state; integration tests with fakes (no notifications yet)
- [ ] M8 — Orchestrator II (SPEC §10.5–10.8): notifications outbox + `tick` (reminders, expiry, batching), invites, saved-bill edits/deletes/"not mine", payments (record, not received, undo, overpay, square-up), reminders, history, stop/start, caps
- [ ] M9 — CLI + FastAPI entrypoints (SPEC §11) incl. API token, README "try it" walkthrough with the fake adapters

**CHECKPOINT B** — final: stop, push, open a PR, notify the user, and summarize.

## Log

- M0: scaffold created by hand. Engine contract frozen in `src/smartsplit/engine/__init__.py`. Commit `fc41671`.
- M1: `split_receipt` (weighted overrides, clamped adjustments, one floor + largest-remainder helper), `fold_item_tax`, `amounts_to_weights`; frozen types moved to `engine/split.py` and re-exported; CI actions on Node 24; 74 tests, 100% coverage; review: no must-fix. Commit `42c46b6`.
- M2: CONTRACTS §1 domain, ports (Repository + UoW, ImageStore, parser/interpreter, clock, ids), `config.py`, Postgres adapter (Core tables, tagged-JSONB codec, advisory lock, Alembic), file ImageStore, in-memory fakes; repository contract tests run on fake and Postgres; 233 tests, 97% coverage; review must-fix (SKIP LOCKED test) fixed. Commit `0f64ca5`. (M3's pure engine commit `1be7666` landed just before it, so `0f64ca5` also contains it.)
- M3: `resolve_rules`, `match_item`, discount links/overrides (linked follow the parent, unlinked are split among everyone), learning (`observe`, `learned_kind`); services for matching (model outside any transaction, aliases per place, model-call count), stated rules with §6.2 permissions and "drinks milk now" deletes, `learn_from_bill`; `Canonicalizer` port + fake; 264 tests, 99% coverage; review must-fix (unlinked discounts) fixed. Range `c993395..16f21a7`. Commit `16f21a7`.
- Checkpoint A fixes (docs/CHECKPOINT_A_REVIEW.md items 1–18): refunds matched by name, exact amounts before tax, weighted learning, serialized claims, rule upsert, one active draft, port constraint errors on both backends, scope derived by the rules service, codec property + JSONB tests, config/README. Review must-fix (asymmetric exact-amount test) fixed. Range `93abd81..b949279` plus the fix-review commit after M4.
- M4: ledger (balances, greedy `simplify_debts`, group/personal pair views, overall with breakdown, payment allocation, iterative square-up) with property tests; review must-fixes (square-up net → Open question, option (a) built and tested; named-context overpayment logged). Range `b949279..41f4cdb`. Commit `41f4cdb`.
- M5: Anthropic vision parser with structured output (one retry; image-vs-setup 400s), shared validation (`services/receipt_output.py`), `FakeReceiptParser` reading recorded-shape fixtures, opt-in live test with a rendered receipt, `pytest-socket` no-network guard; review must-fix (client factory untested) fixed. Range `41f4cdb..(M5 close-out)`.

## Follow-ups

(non-blocking review findings go here)

- (M1 review) `amounts_to_weights` raises on no fixed amounts: the orchestrator (M7) must use a plain list override for an equal split, never route "no exact amounts" here.
- (M2 review) The fake `claim_due` returns a `requested_reply` for a recipient who doesn't exist, while Postgres (inner join, FK) can't store one; the fake skips FK checks generally. Harmless today.
- (M2 review) Services must use `drafts.update(draft, expected_state=...)` and handle `StaleDraftError` (M7/M8).
- (M3 review) The orchestrator must add `MatchedLines.model_calls` to `LlmUsage` and check the daily limit before matching (M7).
- (M3 review) A linked discount shares its parent's key, so a `soft_exclude` would make the engine ask twice; the orchestrator should ask about linked discounts only through the parent line (M7).
- (Checkpoint A, M5/M7) Strip or reject NUL (`\x00`) in inbound text and parser output before it reaches the DB (Postgres rejects it); test.
- (Checkpoint A, M7) Build `find_likely_duplicate` / `DuplicateCandidate` in engine per CONTRACTS §2 (C11).
- (Checkpoint A, M7) A group rule can name a subject who isn't a member; resolve names against members in M7.
- (Checkpoint A, M8) `claim_due`: rows dropped by the cap still use `limit` slots within one batch.
- (Checkpoint A) `split_receipt` accepts `bool` amounts (`True` = 1 cent); optionally reject non-int amounts.
- (Fix review, M7) Run the "model never called inside a unit of work" check against the orchestrator, not only the matching helpers.
- (Fix review, M8) Call `claim_due` only in its own unit of work with no conversation lock (lock order).
- (M5 review, M7) Give `FakeReceiptParser` a way to raise `LlmUnavailableError` and to refuse unsupported image types, for the orchestrator's "try again" tests.
- (M5 review) 429/529 are retried at once; honouring `retry-after` (capped by the timeout) would make the one retry likelier to succeed.
- (M5 review) Adapter tests import `httpx2`, which comes with `anthropic`; declare it if a future SDK drops it.
- (M3 review) Stated rules only normalize the item ("I don't drink MLK" → `mlk`); decide in M6/M7 whether stated items go through `match_item`/the model.
