# SmartSplit

Snap a receipt, and it splits each item between the people who actually use it.
It remembers house rules like "don't add milk to Raj", asks when it isn't sure,
and keeps a running ledger of who owes whom. It's self-hostable and open source.
A WhatsApp bot front end is planned.

> Status: revision 2 built: the bot is a conversation agent (CLI and HTTP API; the WhatsApp gateway is not built yet). See `PROGRESS.md` and `docs/SPEC.md`.

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

### Models and cost

Chat (the agent loop and item-name matching) runs on `claude-haiku-5-5`
(`SMARTSPLIT_LLM_MODEL`); receipt photos are read by `claude-sonnet-5-5`
(`SMARTSPLIT_RECEIPT_MODEL`), since a misread goes straight into the numbers. Measured on the
live scenarios (21 conversations, about 80 messages, 2026-11-24): about $0.0005 per chat
message on Haiku (about $0.007 with Sonnet as the chat model) and about $0.005 per receipt
photo; a full live run costs about $0.06, with the cached
system prompt and tools making up most of each call's input. Daily caps:
`SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY` and `SMARTSPLIT_LLM_CALLS_PER_DAY`.

The live scenarios are opt-in and cost a few cents per run:

```bash
SMARTSPLIT_LIVE_LLM=1 uv run pytest tests/live                       # chat on Haiku
SMARTSPLIT_LIVE_LLM=1 SMARTSPLIT_LIVE_CHAT_MODEL=claude-sonnet-5-5 uv run pytest tests/live
SMARTSPLIT_LIVE_VERBOSE=1 ...                                         # print every conversation
```

They print a usage table per model, the questions the bot asked and the cost per message.

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

- `POST /v1/messages` takes the gateway's message and returns the replies to deliver. The
  body may also carry `quoted_text` (the start of the message being replied to), `mentions`
  (`[{"ref", "name", "phone"}]`, with the text naming them as `@<ref>`; leave out the bot's
  own mention, which `addressed_to_bot` already says) and an `event`
  (`{"kind": "bot_added"}` or `{"kind": "participant_left", "subject_ref": ...}`).
  A chat that stays busy longer than `SMARTSPLIT_LOCK_WAIT_SECONDS` gets `503` with
  `Retry-After`: retry the same message. Every other outcome is `200`.
- `POST /v1/tick` returns `{"batch_id", "messages"}`; deliver the messages, then
  `POST /v1/tick/{batch_id}/ack`. A batch not acknowledged within 2 minutes comes back.
- `GET /healthz` (the process is up) and `GET /readyz` (the database answers and is migrated)
  are open. `GET /v1/groups/{id}/balances`, `GET /v1/people/{id}/balances` and
  `GET /v1/people/{id}/rules` are operator reads.
- Each message logs one line (`smartsplit.turns` logger) with a hash of the chat, the outcome,
  steps, tools, tokens and latency, and never any message text, names or numbers.

## Deploy it

```bash
cp .env.example .env                 # set SMARTSPLIT_API_TOKEN, the API key and SMARTSPLIT_BOT_LINK (required)
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose --profile app up -d --build
curl -s localhost:8000/readyz        # {"status":"ready"} once migrations ran
```

The app container runs migrations at start (under a lock, so several workers can start
together), listens on `127.0.0.1:8000` and keeps receipt images in the `images` volume.
Put a TLS proxy in front of it before exposing it. Postgres is bound to `127.0.0.1` only.

### The tick timer

`tick` must run every minute: it sends notifications, nudges and expires idle bills and prunes
old chat. Without it nothing is delivered and drafts never expire. The chat gateway calls
`POST /v1/tick` every minute, sends the batch, and acknowledges it. Without a gateway, run the
CLI's tick from cron or a systemd timer, inside the app container so it uses compose's database
settings; it prints the messages (to the log) and acknowledges them:

```bash
# crontab -e
* * * * * cd /srv/smartsplit && docker compose --profile app run --rm --no-deps app smartsplit tick >> tick.log 2>&1
```

```ini
# /etc/systemd/system/smartsplit-tick.service
[Service]
Type=oneshot
WorkingDirectory=/srv/smartsplit
ExecStart=/usr/bin/docker compose --profile app run --rm --no-deps app smartsplit tick

# /etc/systemd/system/smartsplit-tick.timer  (then: systemctl enable --now smartsplit-tick.timer)
[Timer]
OnCalendar=*-*-* *:*:00
[Install]
WantedBy=timers.target
```

### Backups and restore

The ledger in Postgres is the source of truth; receipt images are the only other state.

```bash
# back up
docker compose exec -T db pg_dump -U postgres -Fc smartsplit > smartsplit-$(date +%F).dump
docker compose --profile app run --rm --no-deps --user root -v "$PWD:/backup" app \
  tar czf /backup/images-$(date +%F).tgz -C /data images

# restore: stop the app first, restore, then start it and check
docker compose --profile app stop app
docker compose exec -T db pg_restore -U postgres -d smartsplit --clean --if-exists < smartsplit-2026-11-24.dump
docker compose --profile app run --rm --no-deps --user root -v "$PWD:/backup" app tar xzf /backup/images-2026-11-24.tgz -C /data
docker compose --profile app start app
docker compose exec -T db psql -U postgres smartsplit -c "select count(*) from bills"
curl -s localhost:8000/readyz
```

Check a restore now and then on a spare machine: the bill count should match and
`/readyz` should say ready.

## How it's built

- `docs/SPEC.md`: the source of truth for behavior and architecture
- `CLAUDE.md`: working rules for the coding agent that builds this project
- `PROGRESS.md` / `DECISIONS.md`: milestone log and decision record
- `scripts/check.sh`: the single quality gate (ruff, mypy --strict, import-linter, pytest + coverage)

## License

MIT
