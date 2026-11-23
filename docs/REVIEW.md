# Milestone review prompt

Give this prompt to a fresh-context subagent after each milestone, with the
milestone name and the diff range `<previous milestone commit>..HEAD`. Each finished
milestone's final commit hash is recorded on its line in the `PROGRESS.md` log (M0 is `fc41671`),
so the range never has to be guessed after a context compaction.

---

You are reviewing milestone **{MILESTONE}** of SmartSplit. You did not write
this code. Read `docs/SPEC.md` and `CLAUDE.md`, then the diff `{RANGE}` and any
files it touches. Be skeptical and concrete.

Check, in order:

0. **Gates are intact:** run `bash scripts/check.sh` and report the result. Grep the diff for
   `noqa`, `type: ignore`, `pragma: no cover`, `pytest.skip`, `xfail`, `skipif`, and for any change to
   `pyproject.toml` `[tool.*]` sections, `.claude/`, `scripts/`, or `tests/acceptance/`. Any loosening of
   lint, types, coverage, import contracts or tests is `must-fix`.

1. **Spec fidelity:** does the code do what SPEC says for this milestone? List every behavior in the spec section that is missing, wrong, or invented beyond the spec.
2. **Correctness:** off-by-one errors, rounding, money as float, unhandled empty or duplicate inputs, state-machine paths with no test, error paths that swallow exceptions.
3. **Tests:** do they test behavior, not implementation? Is any spec rule untested? Are there assertions that can't fail? Mocks where a fake belongs?
4. **Design:** layer violations the linter can't see (for example business logic in an adapter or entrypoint), duplicated logic, functions doing two things, premature abstraction, files over ~300 lines.
5. **Hygiene:** dead code, TODOs, commented-out code, unclear names, missing docstrings on public functions, dependencies added without a DECISIONS.md entry.

Output a list of findings. Each finding has: severity (`must-fix` | `should-fix` | `nit`),
file:line, the problem in one sentence, and the fix in one sentence. `must-fix` is only
for spec deviations, correctness bugs, and missing tests for spec rules. If there are
no must-fix findings, say so explicitly.
