# Checkpoint A — independent review of M1–M3 (2026-11-23)

Three fresh-context reviewers checked `effcadf..93abd81`: (1) adversarial money math, (2) spec and
contract fidelity, (3) persistence and test quality. Results: **no money bugs** (3000-example property
checks per function against an independent model of SPEC §5, up to 60 members and 10^12 cents); code
matches CONTRACTS field for field; no rule violations; frozen files untouched; gate green.

Everything in **Fix now** must be done before M4 starts (tests first, gate + CI green, review gate on
the fix commits). Items in **Follow-ups** go to PROGRESS.md Follow-ups.

## Fix now

### Decisions by the user (2026-11-23)
1. **Refund lines.** An unlinked negative line is matched by name like any item and follows that item's
   rules ("PROTEIN POWDER REFUND" → protein powder → Sam's `only` rule applies). Generic coupons that
   match nothing behave as now (no rules → shared by everyone). Only lines with `discount_for` set **and**
   `amount_cents < 0` get discount-link treatment. (`engine/overrides.py:173`, `services/matching.py:65`.)
   Update SPEC §6.4 and E10/E11/E15 in USE_CASES; tests for refund-follows-rule, generic coupon, positive
   line with a bogus `discount_for`.
2. **Exact amounts are before tax and tip.** "Sam's part was ₹100" on a taxed line means ₹100 of the line
   price; Sam also pays his share of that line's tax and of the tip (e.g. ₹110). This is what the code
   already does (weights from the pre-tax line, applied to the folded line); state it in SPEC §5.2 and add
   an end-to-end test (amounts_to_weights → fold_item_tax → split_receipt).

### Must-fix
3. **Learning on weighted lines** (`engine/learning.py:14-21`). Keep the code's behaviour (someone removed
   from a weighted line counts as `excluded`; people on a weighted line count as `included`); fix the
   docstring, reword SPEC §6.5 ("people on a weighted line count as included"), log in DECISIONS, add the test.
4. **`claim_due` breaks the per-person daily cap under concurrency** (`adapters/db/ledger_stores.py:183-215`).
   Take a transaction-level advisory lock (constant claim id) at the start of `claim_due`, and add the
   two-connection test (one recipient, 6 unsent, cap 2, two overlapping claims → 2 total).

### Should-fix (cheap now, prevents M7/M8 bugs)
5. `RuleStore.put`: use `INSERT … ON CONFLICT (scope_kind, scope_ref, subject_id, item_key) DO UPDATE`
   (two concurrent puts on one slot currently raise IntegrityError).
6. One active draft per conversation in the DB: partial unique index on `(channel, ref) WHERE state IN
   ('awaiting_people','parsing','reviewing')` (new Alembic migration), same check in the fake, contract test.
7. Fake ↔ Postgres parity: the fake checks foreign keys and the conversation `group_or_person` constraint;
   define a port-level `DuplicateKeyError` (and `MissingReferenceError` if needed) raised by both backends;
   run the constraint tests on both.
8. `services/rules.py:77-81` `_is_current_member`: `joined_at <= now and (left_at is None or left_at > now)`;
   fix the test that relies on the inconsistency.
9. `services/matching.py:64-75`: add keys created by the model to the known set while matching one receipt,
   so near-duplicate lines on the same receipt don't call the model twice; test.
10. Test that `canonicalize` is never called while a unit of work is open.
11. `add_stated_rule` derives the scope itself from (conversation kind, group, speaker, subject) so callers
    can't pass `Everywhere()` from a group chat.
12. Hypothesis round-trip test for the codec (commands, prompt payloads incl. nested effects, overrides,
    lines, notification args, messages; mixed timezones), plus a Postgres JSONB pass.
13. Missing negative tests: duplicate `ProcessedMessage` key raises; duplicate `ChatIdentity` raises;
    `StaleDraftError` across two real connections; `claim_due` with a notification sent exactly at `day_start`.
14. Postgres fixtures move from `tests/repository/conftest.py` to `tests/conftest.py`.
15. `test_a_second_message_waits_for_the_lock`: assert the worker is still blocked (alive / `pg_locks`), not
    just a timeout. Add an Alembic upgrade → downgrade → upgrade test and `pg_indexes` assertions for the
    partial indexes.
16. README quick start: `.env` isn't loaded; document `uv run --env-file .env …` (or `set -a; source .env`).
17. Config: an empty `ANTHROPIC_API_KEY` loads as None; `test_defaults_and_secrets` clears `SMARTSPLIT_*`
    first; `invite_template` default matches `.env.example`.
18. Docs: SPEC §5.2 signature matches CONTRACTS (`Sequence[tuple[str, Cents]]` → `tuple[Weight, ...]`);
    `amounts_to_weights` docstring says leftover cents go by member order (+ test where `others` order differs);
    add `observe` to CONTRACTS §2; docstring on `Match`.

## Follow-ups (log in PROGRESS.md)
- (M5/M7) Strip or reject NUL (`\x00`) in inbound text and parser output before it reaches the DB (Postgres rejects it); test.
- (M7) Build `find_likely_duplicate` / `DuplicateCandidate` in engine per CONTRACTS §2 (C11).
- (M7) A group rule can name a subject who isn't a member; resolve names against members in M7.
- (M8) `claim_due`: rows dropped by the cap still use `limit` slots within one batch.
- A learned rule is only undone by stating or deleting a rule; later `included` answers just stop a new streak (log in DECISIONS).
- `split_receipt` accepts `bool` amounts (`True` = 1 cent); optionally reject non-int amounts.
- `match_item` with threshold 0 lets empty names match anything; raise the config minimum to 1.
