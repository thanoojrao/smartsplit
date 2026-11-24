# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

M10 (agent core) is done: read DECISIONS "M10 — agent core" for how it differs from CONTRACTS. **Next: M11
(production flow)**, per its line below: photo checks before the read (member, limits, size) and
`not_a_receipt` silent in groups; group gating (addressed, receipt photos, waited-on people for 10 minutes
after the bot posted), mentions (`@<ref>` → `@Name`, handles for mentioned people, add by mention), quoted
replies (refs of the quoted bot message first), `bot_added` intro + reply-to-join, `SMARTSPLIT_BOT_LINK` in
"message me 1:1 first"; install-wide daily cap and "limit reached" once a day; bounded lock wait (503 +
`Retry-After`) and `tick` try-lock; `TickBatch` + ack API; `/readyz`; the per-turn log line (use
`LoopResult`); Dockerfile, compose app service, tick timer, backup/restore in README. Then M12, then
CHECKPOINT C. The user's own name stays in `docs/USE_CASES.md`, `docs/USE_CASE_TRACE.md` and `LICENSE` by their choice.

## Milestones

- [x] M0 — Scaffold: spec, tooling, quality gate, frozen engine contract + acceptance tests
- [x] M1 — Split engine (SPEC §5): `split_receipt` incl. weighted overrides, `fold_item_tax` (§5.1), `amounts_to_weights` (§5.2); all acceptance tests pass + own unit tests (negative subtotals, many members, large amounts, weights, exact amounts, validation)
- [x] M2 — Domain model, messages and commands (CONTRACTS §1) + ports incl. ImageStore with unit of work (CONTRACTS §4) + `config.py` + Postgres adapter with Alembic migration + filesystem ImageStore (add `adapters.files` to the independence contract) + repository tests against real Postgres
- [x] M3 — Rules and matching (SPEC §6): scopes, `resolve_rules`, item matching with per-scope aliases and discount linking, learning, with a fake LLM canonicalizer

**CHECKPOINT A** — stop, push, notify the user, and summarize. The core logic is reviewed by the human before anything is built on top of it.

- [x] M4 — Ledger (SPEC §9): context balances incl. settlements, group `simplify_debts`, personal pairs, overall view, payment allocation, square-up
- [x] M5 — Receipt parsing (SPEC §7): port + Anthropic adapter + fixtures + opt-in live test; quantity, taxed, discount_for, confidence, validation
- [x] M6 — Command interpreter (SPEC §8): full command set, Anthropic adapter (tool use) + keyword fake
- [x] M7 — Orchestrator I (SPEC §10.1–10.4, 10.7, §12.2–12.3): reacting rules, identity + onboarding + membership, group and personal bill flows, prompts, review edits, confirm, cancel, queue, duplicates, privacy routing, balances queries; idempotency + serialization; DB-backed state; integration tests with fakes (no notifications yet)
- [x] M8 — Orchestrator II (SPEC §10.5–10.8): notifications outbox + `tick` (reminders, expiry, batching), invites, saved-bill edits/deletes/"not mine", payments (record, not received, undo, overpay, square-up), reminders, history, stop/start, caps
- [x] M9 — CLI + FastAPI entrypoints (SPEC §11) incl. API token, README "try it" walkthrough with the fake adapters

**CHECKPOINT B** — final: stop, push, open a PR, notify the user, and summarize.

Revision 2 (SPEC §8: the conversation agent; approved by the user).

- [x] M10 — Agent core, offline (SPEC §4.4–4.5, §8, §10.2–10.8, §12.3; CONTRACTS §1, §4.2, §5): `AgentModel` port and `ScriptedAgent`; tool argument dataclasses with generated schemas, handles and `Money` strings; tools over the existing services returning results + shown blocks; transcript with refs for every outbound message (replies, DMs, group posts, notifications, tick messages), compact storage, pruning; pending actions (later turn, right person, same chat, 30 min, version, supersede) and the `confirm_draft` rules; draft `version`, line numbers that never shift, one active draft per adder, `awaiting_people` for unknown names; the loop in `handle` (one locked transaction, tools-off last step, deadline, rollback); group-turn privacy; reply clean-up (handles → names, markdown, numbers); `smartsplit demo`. Retire the first build's interpretation stack: `domain/commands.py`, `CommandInterpreter`, `services/{intents,dispatch,routing,answers,context}.py`, `adapters/llm/{commands,command_tools}.py`, `adapters/fakes/{phrases,interpreter}.py`, the 7 old prompt kinds, `requested_reply`, the `parsing` state and its retries, `Conversation.last_listed_bill_ids`, question batches. Integration tests re-expressed as state, shown-block and transcript checks, plus loop tests (multi-step, tool errors the model recovers from, rollback, limits, injection)
- [ ] M11 — Production flow (SPEC §7, §10.1–10.3, §10.8, §11, §12): photos read on arrival into `PhotoRead` (own transaction, reused on retry, `not_a_receipt` silent in groups, checks before the read, last-photo pickup); group gating (addressed, receipt photos, waited-on people for 10 minutes), mentions, quoted replies, `bot_added` intro and reply-to-join, `SMARTSPLIT_BOT_LINK`; usage counted in its own transactions, install-wide daily cap; message deadline and bounded lock wait (503 + `Retry-After`); `tick` with try-lock, `TickBatch` and ack; `/readyz`; per-turn log line; Dockerfile, compose app service, `tick` timer, backup and restore in the README
- [ ] M12 — Anthropic agent adapter (SPEC §8.7, §12.5): tool use on `claude-sonnet-5-5` with the cached prefix, tools-off last step, per-call timeout from the deadline; system prompt (reply style, one question at most, defaults, untrusted data); live scenarios for L1–L5, L7, L11, L16 and the main flows of C, D, G, H and I, counting questions asked; usage table and cost per message; README/CLI updates

**CHECKPOINT C** — stop, push, open a PR, notify the user, and summarize (including live results and cost per message).

## Log

- M0: scaffold created by hand. Engine contract frozen in `src/smartsplit/engine/__init__.py`. Commit `fc41671`.
- M1: `split_receipt` (weighted overrides, clamped adjustments, one floor + largest-remainder helper), `fold_item_tax`, `amounts_to_weights`; frozen types moved to `engine/split.py` and re-exported; CI actions on Node 24; 74 tests, 100% coverage; review: no must-fix. Commit `42c46b6`.
- M2: CONTRACTS §1 domain, ports (Repository + UoW, ImageStore, parser/interpreter, clock, ids), `config.py`, Postgres adapter (Core tables, tagged-JSONB codec, advisory lock, Alembic), file ImageStore, in-memory fakes; repository contract tests run on fake and Postgres; 233 tests, 97% coverage; review must-fix (SKIP LOCKED test) fixed. Commit `0f64ca5`. (M3's pure engine commit `1be7666` landed just before it, so `0f64ca5` also contains it.)
- M3: `resolve_rules`, `match_item`, discount links/overrides (linked follow the parent, unlinked are split among everyone), learning (`observe`, `learned_kind`); services for matching (model outside any transaction, aliases per place, model-call count), stated rules with §6.2 permissions and "drinks milk now" deletes, `learn_from_bill`; `Canonicalizer` port + fake; 264 tests, 99% coverage; review must-fix (unlinked discounts) fixed. Range `c993395..16f21a7`. Commit `16f21a7`.
- Checkpoint A fixes (docs/CHECKPOINT_A_REVIEW.md items 1–18): refunds matched by name, exact amounts before tax, weighted learning, serialized claims, rule upsert, one active draft, port constraint errors on both backends, scope derived by the rules service, codec property + JSONB tests, config/README. Review must-fix (asymmetric exact-amount test) fixed. Range `93abd81..b949279` plus the fix-review commit after M4.
- M4: ledger (balances, greedy `simplify_debts`, group/personal pair views, overall with breakdown, payment allocation, iterative square-up) with property tests; review must-fixes (square-up net → Open question, option (a) built and tested; named-context overpayment logged). Range `b949279..41f4cdb`. Commit `41f4cdb`.
- M5: Anthropic vision parser with structured output (one retry; image-vs-setup 400s), shared validation (`services/receipt_output.py`), `FakeReceiptParser` reading recorded-shape fixtures, opt-in live test with a rendered receipt, `pytest-socket` no-network guard; review must-fix (client factory untested) fixed. Range `41f4cdb..0b0bdbe`. Commit `0b0bdbe`.
- M6: one tool per command (plain, within the documented structured-output limits), schemas from the dataclasses, decode via the domain codec, `canonicalize` with structured output, keyword fake for tests/demo, `check_amounts`; review must-fixes (strict-tool limits, Unknown text, missing phrases) fixed. Range `ecb1156..3d2f47d`. Commit `3d2f47d`.
- M7: orchestrator `handle` (model calls outside the lock, one locked transaction per message with idempotency, refusals rolled back, receipts read after commit), group/personal bill flows with queue, duplicates, who-with, review edits, numbered question batches, confirm/cancel/save with learning, onboarding and membership, rules in chat with restated changes, balances with privacy; integration tests on fakes plus a Postgres tour and concurrent confirms; review must-fixes (15) fixed. Range `3d2f47d..7986fd4`. Commit `7986fd4`.
- M8: outbox + `tick` (one message per person rendered at send time, numbered batches, invites once, daily cap by local day, reminder after 24 h and expiry after 3 days, quiet retries of unread receipts), saved-bill edit/delete/not-mine as reversal + new bill after a restated yes, payments with allocation, disputes, undo, overpay credit and square-up pinned to a ledger version, remind, history, stop/start; review must-fixes (5) fixed. Range `7986fd4..2eeadaa`. Commit `2eeadaa`.
- M9: one composition root (config → orchestrator, migrations under a lock), Typer CLI (person/group/member/receipt/say/balances/rules/tick/images prune, `--live`), FastAPI app (messages, tick, operator reads, bearer token in constant time, body and field limits, explicit offline mode), README walkthrough; user-approved import-contract change (indirect imports only); review must-fixes (4) fixed. Range `2eeadaa..a4b98c4`. Commit `a4b98c4`.
- M10: the conversation agent offline: `AgentModel` port + `ScriptedAgent`; ~30 tools over id-based services (handles, `Money` strings, generated schemas, savepoint per call); transcript with refs for every outbound message; pending actions and `confirm_draft` rules in code; photos read on arrival (`PhotoRead`); versioned drafts, one active per adder, `awaiting_people`; loop with tools-off final step, deadline and rollback; reply clean-up; `smartsplit demo`; migration 0003; Anthropic agent/canonicalizer adapters (tuned in M12); old interpretation stack removed; review must-fixes (4) fixed. Range `e4b2f78..31bab22`. Commit `31bab22`.

## Follow-ups

(non-blocking review findings go here)

- (M1 review) `amounts_to_weights` raises on no fixed amounts: the orchestrator (M7) must use a plain list override for an equal split, never route "no exact amounts" here.
- (M2 review) The fake `claim_due` returns a `requested_reply` for a recipient who doesn't exist, while Postgres (inner join, FK) can't store one; the fake skips FK checks generally. Harmless today.
- (M3 review) A linked discount shares its parent's key, so a `soft_exclude` would make the engine ask twice; the orchestrator should ask about linked discounts only through the parent line (M7).
- (Checkpoint A, M8) `claim_due`: rows dropped by the cap still use `limit` slots within one batch.
- (Checkpoint A) `split_receipt` accepts `bool` amounts (`True` = 1 cent); optionally reject non-int amounts.
- (Fix review, M7) Run the "model never called inside a unit of work" check against the orchestrator, not only the matching helpers.
- (Fix review, M8) Call `claim_due` only in its own unit of work with no conversation lock (lock order).
- (M5 review) 429/529 are retried at once; honouring `retry-after` (capped by the timeout) would make the one retry likelier to succeed.
- (M5 review) Adapter tests import `httpx2`, which comes with `anthropic`; declare it if a future SDK drops it.
- (M6 review) Literal/enum casing is handled in the codec; apostrophe variants in the keyword fake. "remove Raj" in the fake reads as removing a line named Raj (acceptable for a fake).
- (M3 review) Stated rules only normalize the item ("I don't drink MLK" → `mlk`); decide in M6/M7 whether stated items go through `match_item`/the model.
- (M7 review) A photo refused after its image was stored (e.g. not a member) leaves an orphaned image until the image store prunes it.
- (M7 review) A model-supplied id is echoed back in "X isn't in Flat 4B": harmless (it resolves to nobody), but a generic refusal would read better.
- (M7) Each group answer re-reads memberships and the directory per message; fine at chat scale, revisit if profiling says otherwise.
- (M8 review) `tick`'s delivery writes `last_listed_bill_ids` without the chat's lock; a turn in that personal chat at the same moment could overwrite it (only the numbering for "details 2" is affected).
- (M8 review) `OrchestratorSettings` repeats defaults from `config.Settings`; M9 builds it from config so there is one source.
- (M8) A model outage leaves a receipt retried every 2 minutes for up to 3 days; a back-off would save calls.
- (M9 review) `rules_chat.scope_label` and `_scope_name` share a group branch; fold them into one helper.
- (M9 review) `member add` for a group that doesn't exist yet creates it with that person in it; refuse instead if that surprises people.
- (M10 review) `LoopResult.steps/tools/usage` are only read by M11's per-turn log line; M11 must use them or drop them.
- (M10 review) "Limit reached" is said on every over-limit message; M11 makes it once a day (SPEC 12.5).
- (M10 review) `domain/tools.py` is ~320 lines of plain argument dataclasses; split the `edit_draft` change variants into their own module if it grows.
- (M11 review) A failed or timed-out turn's log line has only its outcome and time: the loop's steps, tools and usage so far are lost with the rollback; carry them out on the exception if debugging needs them.
- (M11 review) `mentioned` creates a person for any mention with a phone, even one sent by a non-member; the gateway must not send the bot's own mention (`addressed_to_bot` covers it). Consider creating people only through `add_person`.
- (M11 review) The 12-hex chat hash in the log line is unsalted; a salt from config would stop someone with the logs and a list of chat ids from matching them.
