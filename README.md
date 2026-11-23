# SmartSplit

Snap a receipt, and it splits each item between the people who actually use it.
It remembers house rules like "don't add milk to Raj", asks when it isn't sure,
and keeps a running ledger of who owes whom. It's self-hostable and open source.
A WhatsApp bot front end is planned.

> Status: first build complete (CLI and HTTP API; WhatsApp gateway not yet). See `PROGRESS.md` and `docs/SPEC.md`.

## Quick start (local)

```bash
uv sync
docker compose up -d db        # Postgres 16 on localhost:5432
cp .env.example .env           # then edit it
set -a; source .env; set +a    # nothing reads .env by itself
bash scripts/check.sh          # lint, types, architecture, tests
```

## Try it (no API key needed)

The CLI is a chat app in your terminal. Offline it uses stand-ins for the model: a keyword
interpreter for chat text, and "receipts" that are recorded model answers
(`tests/fixtures/receipts/*.json`). Everything is stored in Postgres, so start it first
(see Quick start; `DATABASE_URL` must be set).

```bash
uv run smartsplit person add Alex +919876500001
uv run smartsplit person add Sam  +919876500002
uv run smartsplit person add Raj  +919876500003
uv run smartsplit group create "Flat 4B" --as Alex
uv run smartsplit member add "Flat 4B" Sam
uv run smartsplit member add "Flat 4B" Raj

uv run smartsplit say "Raj doesn't drink milk" --as Raj --in "Flat 4B"
uv run smartsplit receipt add tests/fixtures/receipts/grocery_taxed_mix.json --as Alex --in "Flat 4B"
uv run smartsplit say "details" --as Alex --in "Flat 4B"
uv run smartsplit say "yes" --as Alex --in "Flat 4B"

uv run smartsplit say "chai 300 with Sam" --as Alex --in personal
uv run smartsplit say "yes" --as Alex --in personal      # Sam's message is printed as [to Sam]
uv run smartsplit say "paid Alex 100" --as Sam --in personal
uv run smartsplit say "yes" --as Sam --in personal
uv run smartsplit balances --as Alex
uv run smartsplit rules --about Raj
uv run smartsplit tick                                     # deliver messages, nudge idle bills
```

Each reply is printed under the chat it went to: `[Flat 4B]`, `[you]`, or `[to Sam]` for
someone else's personal chat. With a real key, add `--live` (e.g.
`uv run smartsplit --live receipt add photo.jpg --as Alex --in "Flat 4B"`) and set
`ANTHROPIC_API_KEY`.

## Run the API

```bash
export SMARTSPLIT_API_TOKEN=...   # required; the API refuses to start without it
uv run uvicorn --factory smartsplit.entrypoints.api.server:from_environment
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/v1/messages -H "Authorization: Bearer $SMARTSPLIT_API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"message_id": "m1",
  "conversation": {"channel": "whatsapp", "ref": "flat"}, "conversation_kind": "group",
  "conversation_name": "Flat 4B", "sender_ref": "+919876500001",
  "sender_phone": "+919876500001", "sender_name": "Alex", "addressed_to_bot": true,
  "text": "help"}'
```

Without `ANTHROPIC_API_KEY` the API runs on the offline stand-ins, like the CLI.
`POST /v1/messages` takes the gateway's message and returns the replies to deliver;
call `POST /v1/tick` every minute or so. `GET /v1/groups/{id}/balances`,
`GET /v1/people/{id}/balances` and `GET /v1/people/{id}/rules` are operator reads.

## How it's built

- `docs/SPEC.md`: the source of truth for behavior and architecture
- `CLAUDE.md`: working rules for the coding agent that builds this project
- `PROGRESS.md` / `DECISIONS.md`: milestone log and decision record
- `scripts/check.sh`: the single quality gate (ruff, mypy --strict, import-linter, pytest + coverage)

## License

MIT
