#!/usr/bin/env bash
# Runs on every Claude Code session start/resume (wired in .claude/settings.json).
# Cloud sessions only: install dependencies and start Postgres. Does nothing locally,
# where you run `docker compose up -d db` yourself.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 1

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

uv sync --frozen --quiet || { echo "session_start: uv sync failed" >&2; exit 1; }

if ! pg_isready -q -h localhost; then
  $SUDO service postgresql start >/dev/null
  for _ in $(seq 1 20); do pg_isready -q -h localhost && break; sleep 0.5; done
fi

as_pg() { $SUDO su postgres -c "$1"; }
as_pg "psql -qtAc \"ALTER USER postgres PASSWORD 'postgres'\"" >/dev/null
for db in smartsplit smartsplit_test; do
  as_pg "psql -qtAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" | grep -q 1 \
    || as_pg "createdb $db"
done

echo "Session ready: deps synced, Postgres 16 running (databases smartsplit, smartsplit_test)."
echo "Next: read docs/SPEC.md, PROGRESS.md, DECISIONS.md, then run: bash scripts/check.sh"
