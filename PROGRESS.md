# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

PAUSED for a product review with the user (no code yet). The decisions so far are under
"Made by the user" and "M1 prep" in `DECISIONS.md`. Agreed plan, in order:
1. ~~Finish walking through the user's vision~~ (done).
2. ~~Thorough read of `docs/SPEC.md` against `DECISIONS.md`; fix every conflict~~ (done: SPEC rewritten).
   Next: agree a new milestone list with the user (the original M2–M8 no longer cover the scope).
3. Rewrite `docs/USE_CASES.md` (current file is an outdated draft) to cover everything.
4. Agree data shapes and contracts (domain model, ports, messages) with the user.
5. Then build, starting with M1 (split engine incl. weighted overrides per SPEC §5).
Don't start a step before the user agrees to the previous one.

## Milestones

- [x] M0 — Scaffold: spec, tooling, quality gate, frozen engine contract + acceptance tests
- [ ] M1 — Split engine (SPEC §5): all acceptance tests pass + your own unit tests for edge cases (negative subtotals, many members, large amounts)
- [ ] M2 — Domain model (SPEC §3–4) + ports (§2) + Postgres adapter with Alembic migration + repository tests against real Postgres
- [ ] M3 — Preference rules + canonicalization + learning (SPEC §6), with a fake LLM canonicalizer

**CHECKPOINT A** — stop, push, notify the user, and summarize. The core logic is reviewed by the human before anything is built on top of it.

- [ ] M4 — Ledger: balances, simplify_debts, settlements (SPEC §9)
- [ ] M5 — Receipt parsing port + Anthropic adapter + fixtures + opt-in live test (SPEC §7)
- [ ] M6 — Command interpreter port + Anthropic adapter (tool-use) + keyword fake (SPEC §8)
- [ ] M7 — Orchestrator state machine with DB-backed state, full integration tests with fakes (SPEC §10)
- [ ] M8 — CLI + FastAPI entrypoints, README "try it" walkthrough with the fake adapters (SPEC §11)

**CHECKPOINT B** — final: stop, push, open a PR, notify the user, and summarize.

## Log

- M0: scaffold created by hand. Engine contract frozen in `src/smartsplit/engine/__init__.py`.

## Follow-ups

(non-blocking review findings go here)
