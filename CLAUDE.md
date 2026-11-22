# CLAUDE.md — SmartSplit

You are building this project autonomously over long sessions. Quality beats speed.
A smaller, clean, fully tested result is better than a large messy one.

## Start of every session (and after every compaction)

1. Read `docs/SPEC.md`, `PROGRESS.md` and `DECISIONS.md`.
2. Run `bash scripts/check.sh` to see the current state.
3. Continue from "Next up" in `PROGRESS.md`.

## Commands

- `bash scripts/check.sh`: the single quality gate. It runs lint, format check, `mypy --strict`, the import-layer contract, and tests with a coverage floor. **"Done" means this exits 0.**
- `uv run pytest tests/unit -q`: fast inner loop.
- Postgres: in cloud sessions the SessionStart hook starts it. Locally, run `docker compose up -d db`. `DATABASE_URL` is in `.env.example`.

## How to work (per milestone)

1. Take the next unchecked milestone in `PROGRESS.md`. Do milestones in order; don't start one before the previous one is done.
2. Write or extend tests first, from the spec. Then implement the smallest clean design that passes.
3. Run `bash scripts/check.sh` until it's green.
4. **Review gate:** spawn a subagent with fresh context, using the prompt in `docs/REVIEW.md`, on the milestone's diff. Fix every finding marked *must-fix*. Log the rest under "Follow-ups" in `PROGRESS.md`.
5. Update `PROGRESS.md`: tick the milestone, add a one-line summary, and rewrite "Next up" so a brand-new session could continue with no other context.
6. Commit with a clear message (`M3: preference rules + canonicalization`) and push. Commit in small steps within a milestone too; never leave work uncommitted at the end of a turn.

## Hard rules

- **Never modify anything in `tests/acceptance/`.** If you believe an acceptance test is wrong, stop and ask (see below).
- Never skip, xfail, delete or weaken a test to get green. Never lower the coverage floor or loosen lint/mypy config.
- Tests marked `db` must **fail**, not skip, when Postgres isn't reachable. Use `TEST_DATABASE_URL`, and give each test a clean schema.
- No network in tests. LLM and DB access go through ports. Unit tests use the fakes in `adapters/fakes`, and DB tests use the real Postgres.
- Money is integer cents. No floats anywhere near money.
- Respect the layering in SPEC §2. Import-linter enforces it, so don't fight it.
- No dead code, no commented-out code, no `TODO` stubs, no speculative abstractions for out-of-scope features.
- Don't add a dependency unless it clearly earns its place, and log the reason in `DECISIONS.md`.
- Never commit secrets. Never commit `.env`.

## Decisions: decide or ask?

**Decide yourself, log it in `DECISIONS.md` (one line: decision + why), and keep going** when the choice is reversible and inside the spec: naming, internal structure, library choice among equivalents, prompt wording, test layout, thresholds.

**Stop and ask the user** (use PushNotification if available, then ask in chat) when:
- an acceptance test or the frozen engine contract (SPEC §5) seems wrong
- the spec is ambiguous in a way that changes user-visible behavior
- something needs a paid service, real account or credential that isn't configured
- you would change the stack, the architecture layers, or the scope
- you're stuck: the same failure after 3 genuinely different attempts

When you ask: first write the question under "Open" in `DECISIONS.md` with 2–3 options and your recommendation, and commit and push. Then ask one concise question. Keep working on anything not blocked by it.

## Checkpoints

`PROGRESS.md` has **CHECKPOINT** lines. When you reach one, stop working, push, send a notification, and post a short summary for the user: what's built, how to try it, and the decisions made. Don't continue until the user replies.

## Style

- Readable over clever. Descriptive names. Docstrings on public functions, saying *why*, not *what*.
- Pure functions in `domain`, `engine` and `ledger`. Side effects only in adapters.
- User-facing bot messages are short, friendly and plain text, written for a group chat.
