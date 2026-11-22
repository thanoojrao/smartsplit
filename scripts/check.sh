#!/usr/bin/env bash
# The single quality gate. "Done" means this exits 0. Do not edit (see CLAUDE.md).
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$1"; }

step "Frozen acceptance tests unchanged"
sha256sum --check --quiet tests/acceptance/CHECKSUMS.sha256

step "Dependencies"
uv sync --frozen --quiet

step "Lint"
uv run ruff check .

step "Format"
uv run ruff format --check .

step "Types (mypy --strict)"
uv run mypy --strict

step "Architecture layers (import-linter)"
uv run lint-imports

step "Tests + coverage (floor 85%)"
uv run pytest --cov=smartsplit --cov-branch --cov-fail-under=85 --cov-report=term-missing:skip-covered

printf '\nAll checks passed.\n'
