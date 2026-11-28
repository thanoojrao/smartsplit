# SmartSplit — WhatsApp gateway (DRAFT, under review with the user)

The gateway connects one dedicated WhatsApp number to the SmartSplit core. It is a translator and a
courier: it turns WhatsApp events into `POST /v1/messages`, delivers the core's replies, and runs the
`tick` loop. **It holds no business logic**: who to answer, what to say and when to stay quiet are the
core's job (SPEC §8–§12). This document is the source of truth for the gateway; SPEC.md stays the source
of truth for the core, and §12.2 there is the contract between them.

Items marked *(proposed)* are recommendations awaiting the user's OK.

---

## 1. Decisions so far

| Decision | By |
|---|---|
| WhatsApp through **Baileys** (unofficial), not the official Cloud API (groups capped at 8 and need an Official Business Account; bot-started messages are paid templates) | user |
| Code in **`gateway/`** in this repo: TypeScript on Node.js LTS, its own quality gate and CI job, a `gateway` service in `docker-compose.yml` | user |
| Linking with an **8-digit pairing code** (works over SSH), QR code as fallback | user |
| Logged out → a clear log line and the **health check fails**; no extra alerting service | user |
| Voice notes, videos, stickers, GIFs → ignored; in personal chats one line: "I can only read text and photos for now" | user |
| A dedicated number, never a personal one; the bot never starts a chat with a stranger (the core guarantees this) | user (earlier) |

## 2. Scope

**In scope:** linking and staying connected; turning incoming WhatsApp messages and group events into
`InboundMessage`s; downloading photos; delivering replies and `tick` batches with "typing…" and safe
pacing; durable queues so nothing is lost or sent twice across restarts; health and logs; Docker and
compose; a manual end-to-end checklist for a real phone.

**Out of scope:** any splitting, rules or wording (core); PDF receipts; reactions as answers; outbound
@mentions; more than one bot number; the official WhatsApp API; a web dashboard.

## 3. Architecture

```
gateway/
  src/
    config.ts        env → typed settings (validated at start)
    wa/              Baileys socket: connect, link (pairing code / QR), reconnect, auth state
    inbound/         WhatsApp message/event → InboundMessage (pure mapping, fixture-tested)
    core/            HTTP client for /v1/messages, /v1/tick, /v1/tick/{id}/ack, /readyz
    queue/           durable inbound + outbound queues (SQLite file in the data volume)
    outbound/        sender: per-chat order, pacing, typing indicator, retries
    health.ts        /healthz for compose / uptime monitors
    log.ts           structured logs without content
    main.ts          composition root
  test/              unit tests with a fake socket and recorded event fixtures; contract tests
  scripts/check.sh   lint, format, tsc --strict, tests with a coverage floor
  Dockerfile
```

- `inbound/` is pure (no I/O) and holds all WhatsApp-specific mapping rules, so most behaviour is tested
  without a phone.
- Only `wa/` imports Baileys. Only `core/` talks HTTP to the core. Lint rules enforce both.
- *(proposed)* Local state is one **SQLite** file plus Baileys' auth files, both in one data volume
  (`GATEWAY_DATA_DIR`). Why: the gateway stays independent of the core's Postgres, and one volume is all
  there is to back up for the gateway.

## 4. Linking and connection

- **First start:** with no saved session and `GATEWAY_BOT_PHONE` set, the gateway requests a pairing code
  and logs it in large text: "Open WhatsApp on the bot's phone → Linked devices → Link a device → Link
  with phone number instead → enter 1234-5678". Without `GATEWAY_BOT_PHONE`, or on `GATEWAY_LINK=qr`, it
  prints a QR code in the logs instead.
- **Session:** saved in the data volume; restarts reconnect without re-linking.
- **Disconnects:** reconnect with exponential backoff (1 s → 60 s, jittered). While disconnected the
  health check reports `degraded` but stays green for up to 5 minutes, then red.
- **Logged out** (the phone unlinked the device, or WhatsApp ended the session): log
  `LOGGED OUT — re-link needed: run the gateway with GATEWAY_RELINK=1`, delete the stale session, health
  check red, and stop processing. `GATEWAY_RELINK=1` starts a fresh link.
- **Banned / restricted:** treated like logged out, with the reason in the log line.

## 5. Incoming: WhatsApp → `InboundMessage`

### 5.1 Which chats

- Personal chats and groups the bot is in.
- Ignored entirely: the bot's own messages (`fromMe`), status updates, broadcast lists, channels
  (newsletters), community announcement groups, calls, system/protocol messages.

### 5.2 Field mapping

| `InboundMessage` field | From WhatsApp |
|---|---|
| `message_id` | the message key id (WhatsApp ids are unique per chat; the core keys on chat + id) |
| `channel` | `"whatsapp"` |
| `conversation_ref` | the chat JID (`…@g.us` for groups, the person's JID for personal chats) |
| `conversation_kind` | `group` for `@g.us`, else `personal` |
| `conversation_name` | the group subject (from cached group metadata); `null` for personal chats |
| `sender_ref` | the sender's JID as WhatsApp gives it (a phone JID or a hidden-id `@lid`) |
| `sender_alt_ref` | the other one, when WhatsApp gives both (phone JID ↔ `@lid`) |
| `sender_phone` | E.164 from the phone JID, when known |
| `sender_name` | the sender's push name; for unknown names, the group-metadata name, else "Someone" |
| `addressed_to_bot` | the bot's JID (phone or hidden id) is in the message's mentions |
| `reply_to_bot` | the quoted message was sent by the bot |
| `quoted_text` | first 200 characters of the quoted message's text, when the message is a reply |
| `mentions` | each mentioned JID other than the bot: ref, name (group metadata / push name), phone if known; the text keeps `@<number>` as WhatsApp sends it, which the core maps by ref |
| `text` | plain text, extended text, or a photo's caption |
| `image` | for photos (including view-once and photos inside ephemeral wrappers): downloaded bytes and MIME type; over `SMARTSPLIT_MAX_IMAGE_BYTES` → not sent, and in personal chats one line "That photo is too big, try a smaller one" |
| `contact` | a shared contact card: name and the first phone number in the vCard; several cards → the first, and in personal chats a line "I'll take one contact at a time" |
| `event` | `bot_added` when the bot is added to a group (or a group with the bot is created); `participant_left` for each person removed or leaving (subject = their JID). Other group events (name change, admins) are not forwarded; the new name arrives with the next message. |

### 5.3 Ignored message types

| Type | Personal chat | Group |
|---|---|---|
| Voice note, audio, video, sticker, GIF | "I can only read text and photos for now" (at most once per 10 minutes per chat) | ignored |
| Document (incl. PDF), location, poll, live location | same line | ignored |
| Reaction, edit, delete ("message deleted") | ignored | ignored |

The hint is sent by the gateway itself, without calling the core.

### 5.4 Ordering and durability

- Each incoming message is written to the inbound queue **before** anything else, then acknowledged to
  WhatsApp (read receipts are not sent *(proposed)*: the bot never shows blue ticks).
- Messages of one chat go to the core **one at a time, in order**; different chats run in parallel (up to
  `GATEWAY_CORE_CONCURRENCY`, default 4).
- While a request is in flight the chat shows "typing…".
- Retries follow SPEC §12.2: only on a network error or 503 (honouring `Retry-After`, backoff up to 2
  minutes, same `message_id`); a 200 is final; 401 and other 4xx are logged and dropped. A message still
  unsent after 15 minutes is dropped with a log line (the moment has passed).
- The replies from a 200 go into the outbound queue in the same local transaction that marks the inbound
  message done, so a crash in between can neither lose nor duplicate them.

## 6. Outgoing: replies and `tick`

- **Sources:** replies to `/v1/messages` and `tick` batches. Each `OutboundMessage` goes to the chat JID in
  its `conversation_ref` (group or personal).
- **`tick`:** every 60 seconds `POST /v1/tick`; the batch's messages are written to the outbound queue,
  then `POST /v1/tick/{batch_id}/ack`. If the ack fails, the next tick returns the same batch; the queue
  ignores messages it already holds (keyed by batch id + position), so nothing is sent twice.
- **Sending:** per chat in order; between any two sends a random pause of
  `GATEWAY_SEND_MIN_DELAY_MS`–`GATEWAY_SEND_MAX_DELAY_MS` (*proposed* 800–2500 ms) and at most
  `GATEWAY_MAX_SENDS_PER_MINUTE` (*proposed* 20) across all chats; short "typing…" before each message.
- **Delivery:** a message is marked sent when WhatsApp accepts it. Failures retry with backoff for up to
  10 minutes, then are dropped with a log line. Sending stops (and the queue waits) while disconnected.
- **Never cold-message:** the gateway sends only to chats that exist in WhatsApp for this number; the core
  already decides who may be messaged.
- Replies are plain text, sent as new messages (not as quoted replies) *(proposed)*.

## 7. Health and logs

- `GET /healthz` on the gateway's own port: 200 `{"whatsapp":"connected","core":"ok","queued_in":0,"queued_out":0}`
  when connected and the core's `/readyz` answers; 503 when logged out, disconnected for over 5 minutes, or
  the core unreachable for over 5 minutes. Compose uses it as the service health check.
- One log line per handled message and per send: chat hash, kind, outcome, latency. Never message text,
  captions, images, vCards, push names or full phone numbers. Pairing codes and QR codes are the only
  "secrets" ever logged, and only during linking.

## 8. Configuration

| Variable | Meaning | Default |
|---|---|---|
| `SMARTSPLIT_API_URL` | core base URL | `http://app:8000` |
| `SMARTSPLIT_API_TOKEN` | same token as the core | required |
| `GATEWAY_BOT_PHONE` | the bot's number (E.164) for pairing-code linking | — (QR if unset) |
| `GATEWAY_LINK` | `code` or `qr` | `code` |
| `GATEWAY_RELINK` | `1` to drop the saved session and link again | `0` |
| `GATEWAY_DATA_DIR` | session + queue volume | `/data` |
| `GATEWAY_CORE_TIMEOUT_SECONDS` | HTTP timeout, above `SMARTSPLIT_MESSAGE_SECONDS` | `SMARTSPLIT_MESSAGE_SECONDS + 15` |
| `GATEWAY_CORE_CONCURRENCY` | chats handled in parallel | `4` |
| `GATEWAY_SEND_MIN_DELAY_MS` / `_MAX_DELAY_MS` | pause between sends | `800` / `2500` |
| `GATEWAY_MAX_SENDS_PER_MINUTE` | global send cap | `20` |
| `GATEWAY_TICK_SECONDS` | tick interval | `60` |
| `SMARTSPLIT_MAX_IMAGE_BYTES` | same limit as the core | core default |
| `GATEWAY_PORT` | health endpoint port | `8080` |

## 9. Running it

- `docker-compose.yml` gains a `gateway` service (depends on `app` being healthy, data volume
  `gateway-data`, health check on `/healthz`). The existing compose `tick` loop is turned off when the
  gateway runs, since the gateway calls `tick`.
- README "Run it on WhatsApp": what you need (spare phone + SIM for the bot, Anthropic API key, an
  always-on machine), first start and linking, adding the bot to a group, re-linking after a logout,
  backups (add the `gateway-data` volume; it holds the WhatsApp session, so treat it as a secret).
- Hosting notes: a small VPS or a home machine; nothing needs to be reachable from the internet (the
  gateway connects out to WhatsApp, and to the core over the compose network).

## 10. Quality

- `gateway/scripts/check.sh`: ESLint (with import restrictions for `wa/` and `core/`), Prettier,
  `tsc --strict`, Vitest with a coverage floor of 85%; a CI job runs it on every push.
- **Unit tests:** the mapper against recorded WhatsApp event fixtures (every row of §5.2 and §5.3); the
  queue, retry and pacing logic with a fake clock; the connection state machine with a fake socket.
- **Contract test (CI):** the gateway against the real core API started in offline mode with the fake
  models (Postgres service), driving a scripted fake socket through the main flows; asserts what the fake
  socket was asked to send.
- **Manual checklist** (`gateway/MANUAL_TEST.md`) the user runs once with a real phone: §11's W-cases.

## 11. Use cases

| # | Situation | Expected |
|---|---|---|
| W1 | First start with `GATEWAY_BOT_PHONE` | Pairing code in the logs; after entering it, "linked" and health green |
| W2 | First start without a phone number | QR code in the logs |
| W3 | Gateway restarts | Reconnects with the saved session; no re-link |
| W4 | Network drop for 2 minutes | Reconnects; messages received meanwhile are handled in order; health stays green |
| W5 | Phone unlinks the bot | "LOGGED OUT — re-link needed" log line; health red; nothing processed |
| W6 | Personal chat: "hi" | Core's reply arrives in that chat, with "typing…" first |
| W7 | Group: chatter not addressed to the bot | Sent to the core (the core decides), which returns nothing; no reply |
| W8 | Group: "@SmartSplit split this" with a receipt photo | Photo downloaded and sent with the caption; the core's summary posted in the group |
| W9 | Group: a reply to one of the bot's messages | `reply_to_bot` and `quoted_text` set; the core answers |
| W10 | Group: "@Sam owes all" mentioning Sam | `mentions` carries Sam's ref, name and number |
| W11 | Contact card shared in a personal chat | `contact` carries name + number |
| W12 | Bot added to a new group | `bot_added` event; the core's intro posted in the group |
| W13 | Someone leaves or is removed from the group | `participant_left` with their ref |
| W14 | Voice note in a personal chat / in a group | One hint line / nothing |
| W15 | View-once receipt photo | Handled like a normal photo |
| W16 | Huge photo | Not sent to the core; one line in personal chats |
| W17 | Message edited or deleted | Ignored |
| W18 | Core busy (503) | Retried with the same id after `Retry-After`; one reply in the end |
| W19 | Core down for 5 minutes | Messages wait and go through in order when it's back; after 15 minutes they're dropped |
| W20 | Gateway crashes after the core replied but before sending | Reply sent after restart, exactly once |
| W21 | `tick` returns 3 notifications | Each delivered to its personal chat, paced; batch acknowledged; never twice |
| W22 | 30 messages to send at once | Paced at ≤ 20 per minute, per-chat order kept |
| W23 | The same WhatsApp message delivered twice by Baileys | Sent to the core once (and the core is idempotent anyway) |
| W24 | Bot removed from a group | Logged; messages for that group fail to send and are dropped |
| W25 | Group renamed | The new name reaches the core with the next message |

## 12. Milestones

- **G1 — Gateway core, no WhatsApp:** project, config, quality gate + CI job, pure inbound mapper with
  fixtures (§5.2–5.3), core HTTP client with the §12.2 retry rules, durable queues, sender with pacing and
  per-chat order, tick loop, health, logs; all tested with a fake socket and fake clock.
- **G2 — WhatsApp connection:** Baileys socket, linking (code + QR), session storage, reconnect and logout
  handling, media download, typing indicator, group metadata cache, LID/phone handling; contract test
  against the core in offline mode.
- **G3 — Running it:** Dockerfile, compose service and health check, README "Run it on WhatsApp", hosting
  and backup notes, `MANUAL_TEST.md`.

**CHECKPOINT D:** the user links a real number and runs `MANUAL_TEST.md` with a test group; fixes from that run.
