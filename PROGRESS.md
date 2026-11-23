# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

PAUSED for a product review with the user (no code yet). The decisions so far are under
"Made by the user" and "M1 prep" in `DECISIONS.md`. Agreed plan, in order:
1. ~~Finish walking through the user's vision~~ (done).
2. ~~Thorough read of `docs/SPEC.md` against `DECISIONS.md`; fix every conflict~~ (done: SPEC rewritten).
   New milestone list agreed (below).
3. ~~Rewrite `docs/USE_CASES.md`~~ (done, awaiting the user's review).
4. Agree data shapes and contracts (domain model, ports, messages) with the user.
5. Then build, starting with M1 (split engine incl. weighted overrides per SPEC §5).
Don't start a step before the user agrees to the previous one.

## Milestones

- [x] M0 — Scaffold: spec, tooling, quality gate, frozen engine contract + acceptance tests
- [ ] M1 — Split engine (SPEC §5): `split_receipt` incl. weighted overrides + `fold_item_tax` (§5.1); all acceptance tests pass + own unit tests (negative subtotals, many members, large amounts, weights, validation)
- [ ] M2 — Domain model (SPEC §4) + ports (§2) + Postgres adapter with Alembic migration + repository tests against real Postgres
- [ ] M3 — Rules (SPEC §6): scopes, `resolve_rules`, canonicalization, learning, with a fake LLM canonicalizer

**CHECKPOINT A** — stop, push, notify the user, and summarize. The core logic is reviewed by the human before anything is built on top of it.

- [ ] M4 — Ledger (SPEC §9): pairwise per-context and overall balances, group balances, `simplify_debts`, settle-up allocation
- [ ] M5 — Receipt parsing (SPEC §7): port + Anthropic adapter + fixtures + opt-in live test; quantity, taxed flag, confidence
- [ ] M6 — Command interpreter (SPEC §8): full command set, Anthropic adapter (tool-use) + keyword fake
- [ ] M7 — Orchestrator I (SPEC §10.1–10.3): identity + onboarding, group and personal bill flows, questions, confirm, cancel, draft queue; DB-backed state; integration tests with fakes
- [ ] M8 — Orchestrator II (SPEC §10.4–10.6): notifications outbox + `tick`, invites, disputes, edit/delete, membership changes, settle-up, reminders, history
- [ ] M9 — CLI + FastAPI entrypoints (SPEC §11), README "try it" walkthrough with the fake adapters

**CHECKPOINT B** — final: stop, push, open a PR, notify the user, and summarize.

## Log

- M0: scaffold created by hand. Engine contract frozen in `src/smartsplit/engine/__init__.py`.

## Follow-ups

(non-blocking review findings go here)
