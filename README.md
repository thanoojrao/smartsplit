# SmartSplit

Snap a receipt, and it splits each item between the people who actually use it.
It remembers house rules like "don't add milk to Raj", asks when it isn't sure,
and keeps a running ledger of who owes whom. It's self-hostable and open source.
A WhatsApp bot front end is planned.

> Status: revision 2 in progress: the bot is a conversation agent (CLI and HTTP API; WhatsApp gateway not yet). See `PROGRESS.md` and `docs/SPEC.md`.

## Quick start (local)

```bash
uv sync
docker compose up -d db        # Postgres 16 on localhost:5432
cp .env.example .env           # then edit it
set -a; source .env; set +a    # nothing reads .env by itself
bash scripts/check.sh          # lint, types, architecture, tests
```

## Try it (no API key needed)

`smartsplit demo` plays a short scripted conversation through the real bot and database:
people join a flat, Raj says he doesn't drink milk, Alex sends a receipt (a recorded model
answer), saves it, and Sam records a payment that waits for his "yes". The model's steps are
scripted, so it needs no key. Postgres must be running (see Quick start; `DATABASE_URL` set).

```bash
uv run smartsplit demo
```

## Talk to it (needs a key)

The bot is a conversation agent: the model reads the recent chat and calls tools; code does
all the money arithmetic and asks for a "yes" before money moves. Set
`ANTHROPIC_API_KEY` (or `SMARTSPLIT_ANTHROPIC_API_KEY`), then:

```bash
uv run smartsplit person add Alex +919876500001
uv run smartsplit person add Sam  +919876500002
uv run smartsplit group create "Flat 4B" --as Alex
uv run smartsplit member add "Flat 4B" Sam
uv run smartsplit receipt add photo.jpg --as Alex --in "Flat 4B" --caption "split this"
uv run smartsplit say "looks right, save it" --as Alex --in "Flat 4B"
uv run smartsplit say "I paid Alex 300" --as Sam --in personal
uv run smartsplit say "yes" --as Sam --in personal
uv run smartsplit balances --as Alex            # operator reads need no key
uv run smartsplit rules --about Sam
uv run smartsplit tick                          # deliver messages, nudge idle bills
```

Each reply is printed under the chat it went to: `[Flat 4B]`, `[you]`, or `[to Sam]` for
someone else's personal chat.

## Run the API

```bash
export SMARTSPLIT_API_TOKEN=...   # required; the API refuses to start without it
export ANTHROPIC_API_KEY=...      # required too
uv run uvicorn --factory smartsplit.entrypoints.api.server:from_environment
curl -s localhost:8000/healthz
curl -s -X POST localhost:8000/v1/messages -H "Authorization: Bearer $SMARTSPLIT_API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"message_id": "m1",
  "conversation": {"channel": "whatsapp", "ref": "flat"}, "conversation_kind": "group",
  "conversation_name": "Flat 4B", "sender_ref": "+919876500001",
  "sender_phone": "+919876500001", "sender_name": "Alex", "addressed_to_bot": true,
  "reply_to_bot": false, "text": "hi"}'
```

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
