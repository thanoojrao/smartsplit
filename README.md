# SmartSplit

Snap a receipt, and it splits each item between the people who actually use it.
It remembers house rules like "don't add milk to Raj", asks when it isn't sure,
and keeps a running ledger of who owes whom. It's self-hostable and open source.
A WhatsApp bot front end is planned.

> Status: early build. See `PROGRESS.md` for what works today and `docs/SPEC.md` for the design.

## Quick start (local)

```bash
uv sync
docker compose up -d db        # Postgres 16 on localhost:5432
cp .env.example .env
bash scripts/check.sh          # lint, types, architecture, tests
```

## How it's built

- `docs/SPEC.md`: the source of truth for behavior and architecture
- `CLAUDE.md`: working rules for the coding agent that builds this project
- `PROGRESS.md` / `DECISIONS.md`: milestone log and decision record
- `scripts/check.sh`: the single quality gate (ruff, mypy --strict, import-linter, pytest + coverage)

## License

MIT
