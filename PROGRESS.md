# Progress

Update this after every milestone. "Next up" must let a brand-new session continue with no other context.

## Next up

Start M1. The scaffold is in place: lint, mypy, import-linter and coverage all pass.
`bash scripts/check.sh` fails only because the 15 tests in
`tests/acceptance/test_split_engine.py` hit `NotImplementedError`. Implement
`split_receipt` in `src/smartsplit/engine/` per SPEC §5 (split it into modules if
that helps, but keep the public names importable from `smartsplit.engine`). Done
when check.sh exits 0.

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
