# SmartSplit — Specification

SmartSplit is a self-hostable, open-source expense splitter for shared houses,
trips and friends. You snap a receipt, and it splits each line item between the
right people, using what it remembers about who uses what ("don't add milk to
Raj", "Sam usually doesn't eat chips"). It asks when unsure, keeps its own
ledger, and talks to people in group chats and in personal (1:1) chats. Later
that chat is WhatsApp; in this build it is a CLI and an HTTP API.

**Revision 2 (approved by the user after the first build, refined in a product pass):** the bot is a
conversation **agent**: the model reads the recent chat and calls tools in a loop until it writes its
reply (§8). Engine, ledger, rules and matching are unchanged. What changes is how a message becomes
actions and replies, and what a production deployment needs around that: one way to refer to things
(the transcript's references, §8.6), photos read on arrival (§7), a gateway contract with explicit
deadlines and failure codes (§12.2), and cost and abuse limits that survive failed turns (§12.5).
The choices made for it are in DECISIONS.md.

This document is the source of truth. If the code and this spec disagree, the
spec wins, unless DECISIONS.md records a change. `docs/USE_CASES.md` lists the
user-facing situations this spec must cover; `docs/DESIGN_REVIEW.md` records how
the pre-build review shaped it.

---

## 1. Scope of this build

**In scope:** the core, end to end, with no WhatsApp:

1. Domain model and Postgres persistence
2. Split engine (pure, deterministic): weighted and exact-amount shares, per-item tax
3. People and identity: phone numbers, chat identities, per-user nicknames
4. Two kinds of bill context: **group** bills (all or some current members) and **personal splits** (added in a 1:1 chat with chosen people)
5. Preference rules with scopes (everywhere, group, adder's notes), item matching and learning
6. Receipt parsing from an image (Claude vision, behind an interface), on arrival
7. A conversation agent: the model reads the recent chat and the current state, and calls tools in a loop (Claude, behind an interface)
8. Ledger: balances per context, overall balances across contexts, debt simplification, payments with allocation, square-up
9. Conversation orchestrator: decides which messages reach the agent, runs the turn, and owns everything the model must not: drafts and their states, engine questions, pending actions and their confirmation rules, notifications, expiry, limits
10. A CLI channel and a FastAPI HTTP API that drive the orchestrator, with the gateway contract a chat gateway builds against (§12.2), plus a `tick` entrypoint for timed work
11. Running it in production: a container image, readiness check, timed `tick`, backups, per-turn operational logs (§12.6)
12. Basic safety for a self-hosted service: a shared API token, idempotent message handling, per-conversation serialization, cost caps

**Out of scope (do not build):** the WhatsApp/Baileys gateway, the Splitwise
sync adapter, payment links, currency conversion, item categories, automatic
reminders, "forget me" (specified in §13, built later), multi-tenant auth and
user accounts, and a web UI. Design for them through the interfaces below, but
write no code for them.

---

## 2. Architecture

Layered, with dependencies only pointing downward. `scripts/check.sh` enforces
this with import-linter, so a violation fails the build.

```
smartsplit/
  domain/        pure dataclasses, enums, money and phone helpers. Imports nothing from smartsplit.
  engine/        split engine, tax folding, amount→weight conversion, rule resolution, name matching. Pure. Imports only domain.
  ledger/        balances, debt simplification, payment allocation, square-up. Pure. Imports only domain.
  ports/         Protocol interfaces: ReceiptParser, Canonicalizer, AgentModel, Repository (with unit of work), ImageStore, Clock, IdGenerator.
  services/      orchestrator, agent loop, tools (one per action, over the use-cases) + use-cases. Imports domain, engine, ledger, ports. Never adapters.
  adapters/
    db/          SQLAlchemy models, repositories, Alembic migrations (implements ports.Repository)
    llm/         Anthropic-backed ReceiptParser, Canonicalizer and AgentModel (implements ports)
    files/       filesystem ImageStore (implements ports.ImageStore)
    fakes/       in-memory/fake implementations of every port, used by tests and `smartsplit demo`
  entrypoints/
    api/         FastAPI app (webhook-style inbound messages + REST reads + tick)
    cli/         Typer CLI channel
  config.py      settings from env (pydantic-settings); read only by entrypoints, injected elsewhere
```

Rules:
- `domain`, `engine` and `ledger` are pure: no I/O, no clock, no randomness, no logging, no environment access.
- Only `adapters/llm` imports `anthropic`. Only `adapters/db` imports `sqlalchemy`/`alembic`/`psycopg`. `fastapi` and `typer` only in their entrypoints.
- `services` depends on ports (Protocols), and gets concrete adapters and settings injected at the entrypoint.
- Wiring happens in one composition root per entrypoint.
- The model only ever reaches the system through tools (§8.2). Tools are plain services: they check
  permissions, compute, store, and return results; they never call the model.
- Services never send messages themselves. `handle` and `tick` return the `OutboundMessage`s to deliver,
  to any conversation (the current chat, a group chat, a personal chat). Messages to people's personal
  chats that are subject to opt-out, caps and holds go through the `Notification` outbox (§10.8). Every
  message sent is also written to the transcript of the chat it goes to (§8.6). So there
  is no Channel port. Data shapes are in `docs/CONTRACTS.md`.

## 3. Conventions

- **Money is integer cents** (`int`) everywhere. Never `float`. Use `fractions.Fraction` internally where exact division matters.
- **One currency per install**, set in config (`SMARTSPLIT_CURRENCY`, ISO code). No group, person or receipt has its own currency. No FX.
- **Phone numbers** are stored in E.164 (`+919876543210`), normalized with the `phonenumbers` library. Numbers without a country code use `SMARTSPLIT_DEFAULT_REGION` (e.g. `IN`).
- **Dates:** bills carry a purchase date; "this month" etc. use `SMARTSPLIT_TIMEZONE`.
- IDs are strings (UUID4 hex) from the `IdGenerator` port, never generated in pure layers.
- Time comes from the `Clock` port.
- Python 3.12+, full type hints, `mypy --strict` clean.
- Files stay under ~300 lines. Functions stay short and single-purpose.

---

## 4. Domain model

### 4.1 People

| Entity | Key fields | Notes |
|---|---|---|
| `Person` | id, display_name, phone, phone_added_by, notifications_enabled, has_used_bot, created_at | `phone` is required and unique: it is the person's identity. `display_name` is their own name (from their chat profile once they use the bot). `notifications_enabled` is turned off by "stop". `has_used_bot` becomes true on their first personal message. |
| `ChatIdentity` | channel, external_ref, person_id | How a person appears in one channel (`whatsapp` number, `whatsapp_lid`, `cli` handle). `(channel, external_ref)` is unique and maps to exactly one person. |
| `Nickname` | owner_id, subject_id, name | What one person calls another ("Sam" for you, "Samuel" for Raj). Unique per (owner, normalized name), so once the speaker says which Sam they mean, the bot remembers it as their nickname. Others only ever see the name *they* gave someone, never the stored display name of a person they share no context with. |

### 4.2 Where bills live

| Entity | Key fields | Notes |
|---|---|---|
| `Group` | id, name, channel_ref (optional, unique) | `channel_ref` links the group to one group chat. |
| `Membership` | group_id, person_id, position, joined_at, left_at (optional) | `position` orders members (rounding ties). *Current* while `left_at` is empty. Rejoining creates a new membership. |
| `Context` | `GroupContext(group_id)` \| `PersonalContext()` | Every bill, receipt, draft and settlement has exactly one context. A personal split has no group; its people are the bill's participants. |
| `Conversation` | key (channel, ref), kind (`group` \| `personal`), name, group_id or person_id | One chat the bot is in. |

### 4.3 Items, matching and rules

| Entity | Key fields | Notes |
|---|---|---|
| `Item` | key | Install-wide set of item keys (`"milk"`), so rules about an item apply everywhere. |
| `ItemAlias` | match_scope, raw_name, item_key | Remembered match from a normalized receipt name to an item key. `match_scope` is `GroupScope(group_id)` or `NotesScope(owner_id)` (personal splits by that adder), so a wrong match only affects that place. |
| `Rule` | id, subject_id, item_key, kind, scope, author_id, source, created_at | `kind`: `exclude` \| `soft_exclude` \| `only`. `scope`: `Everywhere` \| `GroupScope(group_id)` \| `NotesScope(owner_id)`. `source`: `stated` \| `learned`. At most one rule per (scope, subject, item_key). |
| `AnswerObservation` | scope, subject_id, item_key, outcome (`excluded` \| `sole_assignee` \| `included`), bill_id, observed_at | What a saved bill's answers showed about one person and one item; the input to learning (§6.5). |

### 4.4 Receipts, bills and payments

| Entity | Key fields | Notes |
|---|---|---|
| `PhotoRead` | conversation, message_id, sender_id, outcome (`receipt` \| `not_a_receipt` \| `unreadable`), receipt_id (optional), used_by_draft_id (optional), created_at | One per inbound photo, written in its own transaction as soon as the photo is read (§7), so a retried or rolled-back message never reads it twice, and a photo sent on its own can be picked up by the next message (§10.4). |
| `Receipt` | id, image_ref, mime_type, merchant, purchased_at, line_items, tax_cents, other_adjustments_cents, total_cents, warnings | The immutable parse record. `other_adjustments_cents` = tip + service charges − receipt-level discounts. Review edits happen on the draft's working copy. |
| `LineItem` | id, position, name, quantity, amount_cents, taxed, confidence, canonical, discount_for, match_how, match_is_new | `amount_cents` is the line total (negative for discount/refund lines). `quantity` ≥ 1. `taxed`: `True`/`False`/`None` (receipt doesn't say). `confidence` 0–1. `canonical`: item key. `discount_for`: id of the line this discount reduces, if the parser could link it. `match_is_new` marks a first-time item match (shown once in the summary). `position` is the line number people see; it never changes within a draft (a removed line leaves a gap, an added line takes the next number). |
| `Bill` | id, context, origin conversation, receipt_id (optional), payer_id, added_by, description, purchased_at, participants (ordered), lines, tax_cents, other_adjustments_cents, total_cents, shares, reverses_id (optional), replaces_id (optional), edit_reason (optional), created_at | Append-only. An edit is a reversing bill (`reverses_id`) plus a new bill (`replaces_id`, `edit_reason`); a delete is only the reversing bill. Shares sum exactly to `total_cents`. |
| `BillLine` | id, position, name, item_key, quantity, amount_cents (before tax folding), taxed, discount_for, assignees (person → weight) | The per-line split as saved; with the bill's tax and adjustments, details and edits can be rebuilt without re-running rules. |
| `Settlement` | id, payment_id, context, from_id, to_id, amount_cents, kind (`payment` \| `square_up`), recorded_by, reverses_id (optional), created_at | One real payment is stored as one row per context it was allocated to, sharing `payment_id`. Reversal ("not received", "undo") writes negating rows. |

### 4.5 Conversation state

| Entity | Key fields | Notes |
|---|---|---|
| `BillDraft` | id, conversation, context, added_by, payer_id, receipt_id (optional), description, purchased_at, working copy of lines / tax / other adjustments / total, participants, overrides, owes_all_id, possible_duplicate_of (optional bill or draft), state, version, created_at, last_activity_at, reminded_at | A bill under review. `version` goes up on every change, so a confirm can check that the adder saw the current split (§8.4). `overrides`: line id → list of people, or {person: weight}, or exact amounts (§5.2). States in §10.4. One active draft per (conversation, adder); up to `SMARTSPLIT_MAX_QUEUED_DRAFTS` more from the same adder wait as `queued`. |
| `Prompt` | id, conversation, draft_id (optional), kind, typed payload, status (`open` \| `answered` \| `dropped`), asked_of (optional: only that person may answer), created_by, created_at, expires_at (optional), answers | What the bot is waiting for that code must track. Two kinds only: `engine_question` (line + member + reason, §5) and `pending_action` (§8.4: the tool and its arguments, the exact effect, the version it was computed on, who must confirm, where, and until when). Clarifications the model asks itself ("which Sam?", "who's this with?") are not prompts: the next turn sees them in the transcript. |
| `ChatMessage` | conversation, seq, sender_id (optional: none for the bot), text, refs, created_at | The chat transcript (§8.6). `refs` lists, in display order, what a bot message showed: bills, the draft and its version, lines, questions, pending actions, people. `seq` comes from one database sequence. |
| `Notification` | id, recipient_id, actor_id, kind, bill_ids, payment_id, args, created_at, sent_at (optional) | Outbox for messages to people's personal chats. Text is rendered when sent (so balances are current). Held while the person hasn't used the bot or has notifications off. |
| `TickBatch` | id, messages, created_at, acked_at (optional) | What one `tick` returned, kept until the gateway acknowledges delivery (§10.8). |
| `ProcessedMessage` | conversation, message_id, replies, processed_at | Idempotency: a repeated inbound `message_id` returns the stored replies and changes nothing. |
| `LlmUsage` | counter (a person id, or `install`), day, calls | Model calls per day, per person and for the whole install (§12.5). Written in its own short transaction per call, so a rolled-back turn still counts. |

Receipt invariant: `sum(line_items.amount_cents) + tax_cents + other_adjustments_cents == total_cents`.
The parser must flag a receipt where this doesn't hold (in `warnings`), not silently fix it.

---

## 5. Split engine contract (FROZEN)

`smartsplit.engine.split_receipt(...)`. The signature and types are importable from
`smartsplit.engine` (defined in `src/smartsplit/engine/split.py`). `tests/acceptance/test_split_engine.py`
pins the behavior and **must not be modified**.

`members` are the bill's participants, in order (group membership order, or the
order chosen for a personal split). `rules` are the already-resolved rules for
this bill (see §6.3); the engine does not know about scopes.

Semantics, in order, for each line item:

1. **Item key** = `item.canonical` if set, else `normalize(item.name)`.
   `normalize` = lowercase, trim, collapse internal whitespace.
2. **Override** for this item id (from the user's answers) → those members, in member order. No questions.
   An override is either a list of members (equal split) or a mapping member → weight
   (positive integer; the item is split in proportion to the weights, e.g. `{"sam": 2, "raj": 1}`).
   A member listed twice in a list override counts once.
   Rules never carry weights; every rule-based assignment is an equal split.
3. Else, if any `only` rules match the key → exactly those members.
4. Else, start with all members, remove members with an `exclude` rule for the key.
   A `soft_exclude` keeps the member and emits `Question(item_id, member_id, SOFT_RULE)`
   (one question per member and item, however many matching rules). A member with both an
   `exclude` and a `soft_exclude` for the key is excluded and gets no question.
5. If the result is empty → assign to all members and emit `Question(item_id, None, NO_ELIGIBLE_MEMBERS)`.

Rules whose `member_id` is not in `members` are ignored.

Then compute amounts:
- Each item is split among its assignees in proportion to their weights (1 each unless an override gives weights), using exact `Fraction`s.
- `adjustments_cents` is allocated in proportion to each member's item subtotal, with negative subtotals counted as 0.
  If every member's clamped subtotal is 0 (for example no items, or only discounts/refunds), it is split equally.
- **Rounding:** floor each member's exact total share (items + adjustments), then hand the leftover cents one at a time to the members with the largest fractional remainders. Break ties by member order. The same rule applies to negative shares.
- Result: `shares` has every member (0 allowed) and sums **exactly** to `sum(items) + adjustments_cents`.

Validation (`ValueError`): an empty or duplicate member list; duplicate item ids; an override
for an item id not in `items`; an empty override; an override naming a non-member; an override
weight that is not a positive integer.

Contract change (approved by the user, see DECISIONS.md): `overrides` accepts
`Mapping[str, Sequence[str] | Mapping[str, int]]`. A list keeps the original equal-split
behaviour, so the original acceptance tests are unchanged.

### 5.1 Per-item tax (pure, in `engine`)

`fold_item_tax(lines: Sequence[TaxedLine], tax_cents: int) -> tuple[list[ItemInput], int]`,
where `TaxedLine(item: ItemInput, taxed: bool | None)`:
- Weights are the amounts of lines with `taxed=True`, negatives counted as 0.
- If those weights sum to more than 0, the tax is spread over those lines in proportion to the
  weights (floor + largest-remainder rounding, ties by line order) and added into their amounts;
  it returns the new items and 0 tax left over.
- Otherwise it returns the items unchanged and the whole `tax_cents` left over.

The orchestrator then calls `split_receipt` with the folded items and
`adjustments_cents = leftover tax + other_adjustments_cents`.

### 5.2 Exact amounts (pure, in `engine`)

`amounts_to_weights(line_cents, fixed: Sequence[tuple[str, Cents]], others: Sequence[str]) -> tuple[Weight, ...]`
turns "Sam's part was ₹100" into a weighted override: fixed people get exactly their amount, and
the remainder is split equally among `others` (leftover cents go by member order, like any split).
Exact amounts are **before tax and tip**: "Sam's part was ₹100" on a taxed line means ₹100 of the line
price, and Sam also pays his share of that line's tax and of the tip (e.g. ₹110). Fixed amounts must be positive and sum to
at most `line_cents`; if they sum to less and `others` is empty, or to more, it raises `ValueError`
and the orchestrator asks. A manual bill with exact amounts for everyone ("rent 30000: Sam 12000,
me 9000, Raj 9000") is one line with every person fixed; the amounts must add up to the total.

---

## 6. People, rules and matching

### 6.1 Identity

- A person is identified by phone number; there are no name-only people. Adding someone the bot
  doesn't know needs their contact card or number.
- Inbound messages are resolved to a person through `ChatIdentity`. The first message from an
  unknown identity with a phone creates the person (name from the chat profile). An unknown
  identity *without* a phone (a WhatsApp hidden id) cannot create a person: the bot asks them to
  message it 1:1 first, which links the hidden id to their number.
- Names the speaker uses ("split with Sam") resolve, for the speaker, in this order: their nicknames,
  then the names of people they share a current group or a past bill with (`find_person`, §8.3).
  Several matches → the bot asks which one, and remembers the answer as the speaker's nickname.
  No match → the bot asks for a contact card or number. A mention that carries a phone needs neither.
- A number the speaker gave for someone can be corrected by that speaker ("Priya's number is …")
  only while that person has never used the bot.
- Bot text never shows full phone numbers (`+91•••••43210`).

### 6.2 Rule scopes and who may change them

| Scope | Created by | Applies to | Who may delete |
|---|---|---|---|
| `Everywhere` | the subject, stating it about themselves in their personal chat | every bill they're in | only the subject |
| `GroupScope(g)` | anyone stating it in group g's chat, or learned from answers in g | bills in group g | any current member of g (announced in the group) |
| `NotesScope(owner)` | the owner, stating it about someone in their personal chat, or learned from the owner's answers there | personal splits the owner adds | only the owner |

- A statement about yourself made in a group chat is a group rule, not an everywhere rule.
- There are three rule kinds only. "Raj drinks milk now" deletes the rule for (Raj, milk) in that scope.
  A group cannot override someone's everywhere rule, but can include them on a specific bill by answering or editing.
- A new stated rule replaces any rule for the same (scope, subject, item key). A learned rule can
  replace a learned rule or a stated `soft_exclude` (consistent answers settle a "usually"), but never a
  stated `exclude` or `only`.
- When a membership ends, that group's rules about the person stop applying (they are kept, and apply again if they rejoin).
- "What rules are about me?" lists every rule with you as subject (scope and author included) — in a
  group chat only that group's rules are shown, and the full list goes to your personal chat (§10.7).

### 6.3 Resolving the rules for one bill (pure, in `engine`)

`resolve_rules(rules, participants, context, added_by)` returns one rule per (participant, item key):
1. Candidates: rules whose subject is a participant, and whose scope is `Everywhere`,
   or `GroupScope` of this bill's group, or `NotesScope(added_by)` for a personal split.
2. If several candidates share (subject, item key), the most specific scope wins
   (`GroupScope`/`NotesScope` over `Everywhere`), then `stated` over `learned`, then the newest.

### 6.4 Matching receipt names to items

Receipt names are messy (`"2% MLK GAL"`). A service maps each line to an item key, using a pure
matcher in `engine` and the `Canonicalizer.canonicalize` port:
1. exact match on the normalized name, or a stored `ItemAlias` in this bill's match scope
   (the group, or the adder's personal splits)
2. deterministic fuzzy match against known item keys (rapidfuzz ratio ≥ `SMARTSPLIT_FUZZY_THRESHOLD`)
3. otherwise ask the LLM `canonicalize(name, known_keys)`.

A match from step 2 or 3 is stored as an `ItemAlias` in that match scope and shown in the summary the
first time ("OAT MLK → milk?"). "That's not milk" removes the alias in that scope, and the line's key
becomes its own normalized name (or the item the speaker names instead).
A discount line linked by the parser (a negative line with `discount_for`) gets the key of the line it
reduces, so it is shared by the same people, and follows that line's answers and edits unless it has
its own. Any other negative line (a refund, or a coupon the parser couldn't link) is matched by its own
name like any item and follows that item's rules ("PROTEIN POWDER REFUND" → protein powder, so Sam's
`only` rule applies); a generic coupon that matches no rule is shared by everyone.

### 6.5 Learning

When a bill is saved, each answer to an `engine_question` (and each review edit of who shares a
line) is recorded as an `AnswerObservation` per person and item key, in the bill's rule scope
(group chat → `GroupScope`; personal chat → `NotesScope(adder)`):
- the person was removed from the line → `excluded`
- the person was the only assignee → `sole_assignee`
- otherwise → `included`

When the last two observations for a (scope, subject, item key) are both `excluded`, create or
replace a learned `exclude` rule; both `sole_assignee` → learned `only`. An `included` observation
breaks the streak. `Everywhere` rules are never learned. People on a weighted line count as `included`
(someone removed from it still counts as `excluded`).

---

## 7. Receipt parsing

- Port: `ReceiptParser.parse(image_bytes, mime_type, currency) -> ParsedReceipt | NotAReceipt`, where `currency` is the install currency.
- **When:** a photo is read as soon as it arrives, before the turn and outside the conversation lock,
  after the cheap checks (known sender, member of the group or a personal chat, under the daily
  limits, under `SMARTSPLIT_MAX_IMAGE_BYTES`). The outcome is stored at once as a `PhotoRead`
  (with its `Receipt`), in its own transaction keyed by (conversation, message_id). A retry of the same
  message, or a turn that rolls back, reuses it.
- Anthropic adapter: one vision call returning structured output against a strict schema, model from
  config. Retries once on invalid output or an API error, if the message deadline (§12.2) leaves time.
- Returns line items in integer cents with quantity, `taxed` (true/false/unknown), `discount_for`
  and a `confidence` per item, plus purchase date, tax, other adjustments and total; or `NotAReceipt`
  for a photo that isn't one (a meme, a selfie).
- Output is validated into domain types: integer cents, quantity ≥ 1, confidence clamped to 0–1,
  at most `SMARTSPLIT_MAX_RECEIPT_LINES` lines, total > 0. Invalid output after the retry → `unreadable`.
- If the invariant in §4 fails, `ParsedReceipt.warnings` says so.
- A receipt in a different currency from the install's gets a warning; nothing is converted.
- Receipt text is untrusted data: it is never treated as instructions (§12.3).
- Tests use recorded fixtures (`tests/fixtures/receipts/*.json`). No network in tests. One opt-in live test runs only when `SMARTSPLIT_LIVE_LLM=1`.

## 8. The conversation agent

Every message that reaches the bot (§10.2) is handled by an **agent loop**: the model reads the chat,
calls tools, sees each tool's result, and decides the next step, until it writes the reply. The model
decides *what to do*; the tools, which are the services of this spec, decide *what is allowed* and do
all the money arithmetic and storage. The model never computes an amount, writes a ledger row,
confirms anything on its own, or chooses where a message goes.

### 8.1 One message, end to end

```
inbound message (deadline: SMARTSPLIT_MESSAGE_SECONDS from arrival)
  → already processed? return the stored replies
  → identify the sender (§6.1); decide whether the bot reacts (§10.2); check the limits (§12.5)
  → photo? read it now, outside the lock, store the PhotoRead (§7)
       (in a group, a photo that isn't a receipt and isn't addressed to the bot ends here: no reply)
  → take the conversation lock (wait at most SMARTSPLIT_LOCK_WAIT_SECONDS, else 503, §12.2)
  → open the unit of work; build the turn input (§8.2)
  → loop, at most SMARTSPLIT_AGENT_MAX_STEPS model calls:
       model → tool calls → run each tool (checks, effects, result) → results back to the model
       (the last allowed call is made with no tools, so the model must write its reply)
  → model ends with its reply text (may be empty: say nothing)
  → replies = welcome (first contact only) + model text + the shown blocks the tools produced (§8.5)
  → append the inbound message and every outbound message to the transcripts (§8.6),
    record ProcessedMessage, commit
```

The model's own tool calls and results are **not** kept between turns; only the visible chat (with its
references) is. Every turn starts from the database's truth, so a restart or a long gap loses nothing.

### 8.2 What the model sees

The cached prefix is the system prompt and the tool definitions (fixed for the install). After it, one
user message holds this turn's input, as data:

- `<state>`: a compact snapshot built fresh from the database, only what nearly every turn needs:
  - the chat (group or personal, its name), today's date, the speaker, whether the welcome was just shown;
  - the people the speaker can name here: in a group, its current and past members; in a personal
    chat, the speaker's ~20 most recent people (`find_person` reaches the rest);
  - each active draft here: who added it, payer, people, per-person totals, total and any difference,
    a possible duplicate, flagged lines, open questions; the full line list only when it has at most
    15 lines (`get_bill` gives the rest); how many drafts are queued;
  - open pending actions here, with who must confirm and until when.
- `<recent_chat>`: the last `SMARTSPLIT_CHAT_HISTORY_MESSAGES` messages of this chat (default 10),
  oldest first: speaker name, time, text; bot messages with their references (§8.6).
- `<message>`: the new message: its text (mentions shown as `@Name`), "[photo: receipt, Toit, ₹1,240,
  12 lines]" or "[photo: not a receipt]" or "[photo: couldn't read it]", "[contact: Priya]", the quoted
  bot message if the person replied to one, or an event ("Raj left the chat").

**Handles.** Short handles stand for things: `P2` a person, `B3` a saved bill, `D1` a draft, `L4` line 4
of a draft, `Q1` an open question, `A1` a pending action, `G1` a group, `T1` a payment. Line handles are the line numbers
people see. The others are numbered per turn, in the order they appear in the input; tool results can
add more (`add_person` returns the new person's handle), and those are valid for the rest of the turn.
The service maps handles to ids and rejects any handle it didn't issue. No internal id or phone number
ever reaches the model; in a group turn, nothing from another context does (§10.7).

### 8.3 Tools

Each tool has a JSON schema generated from its argument dataclass, checks its own permissions (§6.2,
§10, §12.3) and returns a result the model reads: `ok`, or a short reason the model can act on ("Priya
isn't in Flat 4B", "two people called Sam: P4 (Flat 4B), P7 (Goa trip)"), the changed state, and any
**shown** text. Arguments use handles for things and decimal strings in major units for money (`"800"`,
`"12.50"`), which code parses into cents; a float, or more decimals than the currency has, is refused.
Tools are deterministic code over the services; they are tested without the model.

| Kind | Tools |
|---|---|
| Read (no effects) | `get_balances` (here, with a person, a group, overall), `get_bill` (a draft or saved bill, line by line), `list_bills` (last N, a period, text such as "Toit", a person), `list_rules` (about a person), `find_person` (a name → candidates) |
| Drafts | `start_receipt` (people or everyone-except, payer, "owes all"; the photo of this message, or this sender's last unused receipt photo here within 10 minutes), `add_manual_bill` (description, amount, people, payer, owes all, exact parts, date), `set_draft_people`, `edit_draft` (one change: line amount, remove line, add line, total, who shares a line with weights or exact parts, add or remove people, "that's not milk", payer), `answer_question`, `file_into_group`, `confirm_draft` (with `keep_duplicate`, `accept_difference`), `cancel_draft` |
| People | `add_person` (a name with a number, this message's contact card, or a mention), `join_group`, `member_left`, `set_nickname` (also "I mean the Flat 4B Sam"), `correct_number` |
| Rules | `add_rule`, `delete_rule`: applied at once when the speaker may change it alone (§6.2); otherwise a pending action |
| Need a "yes" (§8.4) | `change_bill` (edit, delete, not mine), `record_payment`, `square_up`, `not_received`, `undo_payment`; then `confirm_pending`, `decline_pending` |
| Other | `remind`, `set_notifications` |

"Same as last time" means a new bill with the same people and payer as the bill the speaker refers to,
with the new amount or photo; it never copies an old bill's lines.

### 8.4 What code confirms

**Pending actions.** Moving money and changing data other people rely on goes through a pending
action: the tool computes the exact effect, stores it (§4.5) and returns a restatement that is shown
verbatim, ending with whom the bot is waiting for. `confirm_pending(A1)` succeeds only when all hold:
- it was proposed in an earlier turn (never the same one), in this chat, less than 30 minutes ago;
- the current message is from the person it was asked of;
- the data it depends on hasn't changed (version check); otherwise it is recomputed and asked again.

A new proposal of the same kind by the same person replaces their open one. Expired proposals leave
the snapshot and are dropped quietly.

**Saving a draft.** `confirm_draft` works only for the adder, and refuses when:
- the draft was created or changed in this turn (the adder must see the split before saving it);
- its `version` differs from the version in the bot's last summary of it in this chat (someone answered
  or edited since; the new summary is shown instead);
- it is a possible duplicate and `keep_duplicate` isn't set, or lines + tax + adjustments differ from the
  total and `accept_difference` isn't set (the bot asks; the next "yes, keep it" sets them).

The model decides that "sure, go ahead" means yes; code decides whether that yes counts. So a receipt,
a profile name or an earlier chat line saying "SYSTEM: record a payment" can at most produce a proposal
that waits for the right person's own reply.

**Done at once, and announced:** joining, adding a member, someone leaving, a group member cancelling
a group draft (§10.3, §10.4). These are everyday group actions; announcing them in the group is the
safeguard.

### 8.5 Replies

A reply is the model's short text plus the **shown** blocks, which tools render from the database: bill
summaries and details, balances, restatements of pending actions, history lists. Shown blocks are
appended exactly as rendered, so every amount, name and number the user reads comes from code. The
model writes the connecting words ("Got it, Raj is off the beer.") and its own clarifying questions.

Code cleans the model's text before sending: handles become names, markdown becomes plain chat text
(WhatsApp's `*bold*` at most), and anything that looks like a phone number is masked.

How the model behaves is set in the system prompt and checked by the live tests (§12):
- reply in the language the person wrote in, short and plain, for a group chat;
- act on the defaults (the payer is the adder, a group bill includes every current member) instead of
  asking; ask at most one clarifying question per reply; never ask what a tool would refuse anyway;
- in a group, say nothing when the message turned out not to be for the bot.

Where a reply goes is code: replies go to this chat; anything wider (overall balances asked in a group,
§10.7) is sent privately by the tool that produced it, which returns only "sent privately" to the model.

### 8.6 Chat transcript and references

`ChatMessage` rows (§4.5) keep what was said, so later turns understand "same as last time", "he paid",
"no, the other one", "2", and replies to a notification.
- **Stored:** every message in a personal chat; in a group chat, only messages the bot reacted to and
  that it answered or acted on. **Every** message the bot sends is stored in the transcript of the chat
  it goes to, whatever produced it: a reply, a group post from a personal chat, a DM from a group turn,
  a notification, a reminder, a draft nudge or expiry.
- **References:** a bot message stores `refs`: what it showed, in display order. The next turns give
  those things handles, so "details on the second one", "not mine" under a notification, or "line 4 is
  120" resolve to exactly what the person saw. A quoted reply (§10.1) points at the bot message it
  quotes, and that message's references come first.
- **Compact:** shown blocks are stored as their first lines plus their references (a 45-line details
  block is not replayed ten times).
- **Limits:** each chat keeps at most `SMARTSPLIT_CHAT_HISTORY_KEEP` messages (default 50), and `tick`
  deletes messages older than `SMARTSPLIT_CHAT_HISTORY_DAYS` (default 30). Logs never contain message
  text (§12.4).

### 8.7 Ports and fakes

- `AgentModel.step(request) -> ModelStep`: one model call; the request is tools (or none, for the last
  allowed step), system prompt, the turn input and this turn's earlier steps with their results; the
  step is either tool calls or final text, plus token usage. The Anthropic adapter uses tool use with
  the fixed tools and system prompt as the cached prefix (§12.5).
- `ReceiptParser` (§7) and `Canonicalizer.canonicalize(name, known_keys)` (§6.4) stay. If canonicalize
  fails inside a turn, the line keeps its normalized name; the turn goes on.
- **Fake:** `ScriptedAgent` plays a test's list of steps (tool calls, then text) and records what it was
  sent, for flows, loops, tool errors, limits and injection tests. Integration tests drive tools through
  it and check state, shown blocks and transcripts; the live tests (§12) check the real model.

## 9. Ledger

All pure, in `ledger`. Inputs are bills (payer, shares) and settlements per context.

- **Member balance per context** = (totals of bills they paid) − (their shares) + (settlements they sent) − (settlements they received).
  Positive means they are owed. Always sums to 0 per context.
- **Group: who owes whom** = `simplify_debts(balances)`: greedy (largest debtor pays largest creditor,
  repeat), deterministic, ties broken by member order. Few transfers, not guaranteed minimal.
  This is the group's pairwise view; it can shift when new bills arrive.
- **Personal splits: who owes whom** = raw pairs: each participant other than the payer owes the payer
  their share, reduced by settlements between that pair. (Personal splits are never simplified across people.)
- **Overall between A and B** = sum over groups of the simplified pair amount between A and B, plus
  their personal-splits pair amount, with a breakdown per context.
- **Payment allocation:** a payment from A to B
  - recorded in a group chat → that group;
  - recorded elsewhere with a named context ("for the trip") → that context;
  - otherwise → the contexts where A owes B (per the views above), largest first, ties broken by the
    context's oldest bill; anything beyond what A owes B goes to the personal-splits context (B now owes A).
- **Square-up between A and B:** writes `square_up` settlements so that every context's amount between
  them becomes 0, and puts the overall net into the personal-splits context. No money changes hands
  overall (the rows net to the overall balance).
- Bills and settlements are append-only. Corrections are new reversing entries, never edits.

## 10. Orchestrator

A channel-agnostic state machine in `services/`, driven by the agent turn (§8.1): the model chooses
the tools, and the tools move the state machine. State lives in the DB, so a restart mid-flow resumes
cleanly. Every state transition is covered by an integration test using the fakes (§8.7), and the
main conversations also by opt-in live tests with the real model.

### 10.1 Messages

- Inbound: `InboundMessage(message_id, channel, conversation_ref, conversation_kind, conversation_name,
  sender_ref, sender_alt_ref, sender_phone (optional), sender_name, addressed_to_bot, reply_to_bot,
  quoted_text (optional), mentions, text | image | contact | event)`.
  - `mentions`: who the text mentions: their ref, name and phone when the gateway knows it. The text
    carries them as `@<ref>`; code replaces each with `@Name` before the model sees it.
  - `quoted_text`: the start of the message being replied to; code matches it to the bot's message in
    the transcript (§8.6).
  - `event`: `participant_left` (with the person's ref) or `bot_added` (the bot was added to a group).
- Outbound: `OutboundMessage(conversation_ref, recipient_id, text)`. Plain text that reads well in a chat
  app: short lines, no tables.

### 10.2 When the bot reacts

- **Personal chats:** every message.
- **Group chats**, from a member or a non-member:
  - a message addressed to the bot (a mention, or a reply to one of its messages);
  - a photo that turns out to be a receipt (§7); other photos are ignored unless addressed;
  - from members only: a message from someone the bot is **waiting on**, if the bot posted in this
    chat in the last 10 minutes. Waiting on: the adder of an active draft here, the people its open
    questions are about (the adder, for "who's this for?"), whoever a pending action here waits for,
    and the person the bot last replied to here.
  - events (`bot_added`, `participant_left`).
- Everything else never reaches the model, is not stored, and gets no reply. A message that reached the
  model only because its sender was waited on, and that the model answered with nothing and no effect,
  is not stored either.

### 10.3 Onboarding and membership

- **First personal message** from an unknown identity: create the person. The reply starts with a short
  fixed welcome (what the bot does, in two lines); anything waiting for them (bills they're in, held
  notifications) is in the state, so the model can mention it.
- **Added to a group** (`bot_added`), or the first message addressed to it in a group it doesn't know:
  create the group linked to that chat, and post a short intro ending "reply to this message with
  'join' to split bills here". Replies to that message are addressed to the bot, so joining needs no
  mention. The person who added the bot or first spoke to it joins at once.
- **Joining is explicit:** "join", or a member adds someone ("add @Priya", or "add Priya" with her
  contact card or number). A mention that carries a phone is enough to add someone. A non-member who
  talks to the bot is offered to join; tools refuse anything else for them until they do.
- **Hidden ids:** someone the gateway knows only by a hidden id can't be created (§6.1); the bot asks
  them to message it 1:1 first, with the one-tap link `SMARTSPLIT_BOT_LINK`.
- **Leaving:** "X moved out" (by anyone), or a `participant_left` event, ends the membership. People
  who left never rejoin by posting; rejoining is explicit.
- Every membership change is announced in the group. No confirmation is needed.
- A leaver is not in new bills; their balance stays until settled and they can still see it.
  In that group's open drafts they are removed from the participants, their prompts are dropped, and the
  draft is re-split and its summary shown again. If the adder of a draft leaves, the draft is cancelled.

### 10.4 Bill flow

```
photo read on arrival (§7) or a typed bill → choose participants → (duplicate check) → match items
  → fold tax → resolve rules → split_receipt → summary (+ questions) → [edits / answers → re-split]*
  → adder confirms on a later message → write Bill + lines + observations → learn → notify → balances
```

**Starting**
- A receipt photo with a caption ("split with Sam, he paid") starts a draft in one message. A photo
  without a caption: in a group, the draft starts with everyone; in a personal chat, the bot asks who
  it's with. A photo sent on its own followed by "split with Sam" works the same: `start_receipt` picks
  up this sender's last unused receipt photo in the chat from the last 10 minutes.
- The draft is created even when some named people are still unknown or ambiguous: it waits in
  `awaiting_people` while the bot asks for a number or which one, so the photo is never lost.
- In a group that has only one member so far, the summary says so and suggests asking others to join.

**Participants**
- Group: all current members by default, or a subset named by the adder ("me and Priya",
  "everyone except Raj"). Only current members can be included. Snapshotted when the draft is created.
- Personal: the speaker plus the people named. "Who's this with?" is the model's question; the state
  lists the speaker's recent people and groups, and the answer ("the usual", "Sam and Raj", "Flat 4B")
  goes to `set_draft_people` (a group name files it into that group).
- **Payer:** in groups, the adder unless they say "Sam paid". In personal splits, always the adder.

**Draft states**

| State | Meaning | Leaves to |
|---|---|---|
| `queued` | waiting behind the adder's active draft in this chat (its receipt is already read) | `awaiting_people` / `reviewing` when the active draft is saved, cancelled or expires; its summary is posted then |
| `awaiting_people` | people not named yet, or a named person not yet known or not yet chosen | `reviewing` |
| `reviewing` | summary shown, questions may be open, edits allowed | `saved` (adder confirms), `cancelled`, `expired` |
| `saved` / `cancelled` / `expired` | terminal | — |

- **Summary (short):** each person's total, who was skipped and why, first-time item matches, flagged
  low-confidence lines (below `SMARTSPLIT_MIN_LINE_CONFIDENCE`), a total difference, a possible
  duplicate, and at most 3 open questions, worded by line ("Line 4, chips: is Sam in?"). The full line
  list comes on request. The reason is shown for group rules and the adder's own notes; for someone's
  `Everywhere` rule the summary only says they were skipped.
- **Review edits:** "line 4 is 120", "remove the bag", "add water 40", "total is 1840", "Raj had none
  of the wine", "2 for Sam, 1 for Raj", "that's not milk". After each change the split is recomputed and
  the summary shown again.
- **Questions:** anyone in the bill's context may answer. An answer changes the current assignment of
  that line (other open questions on it stay open); if people answer differently, the latest answer
  wins. The next open question is shown once one is answered. The adder can confirm with questions
  still open; the split shown is used.
- **Duplicates:** if a saved bill (not reversed) or another open draft in the same group (or between the
  same people) has the same total within 3 days, the summary says so ("looks like Sam already added
  this"); saving needs the adder's "keep it" (§8.4).
- **Total mismatch:** while lines + tax + adjustments differ from the total, the summary shows the
  difference; the adder fixes a line or accepts it, and it is then shared like tip (§8.4).
- **Confirm:** only the adder, on a later message than the summary it confirms (§8.4).
- **Cancel:** any current member (group) or the adder (personal) can cancel at any time; in groups the
  bot says who cancelled. Cancelling starts the adder's next queued draft.
- **Reminder and expiry:** after 24 hours without activity one reminder is posted in the draft's chat;
  after 3 days the draft expires with a short message there. Nothing is saved until confirmed.
- **Filing into a group** ("add to Flat 4B") from a personal chat: the speaker must be a current
  member; the draft's context becomes that group, rules are re-resolved with that group's rules and
  any new questions are asked in the personal chat; the adder confirms there; the saved bill's summary
  is posted in the group (and stored in its transcript).

### 10.5 After saving: notifications and edits

- **Group bills:** the summary and new balances are posted in the group chat; no personal messages.
- **Personal splits:** every other participant gets a notification: the bill, their share and their new
  overall balance with the payer. They can reply in their own words: details, "not mine", an edit, or
  nothing. Several bills to one person within one `tick` become one message listing each bill.
  Participants who have never used the bot are not messaged; the adder gets a short forwardable invite
  with `SMARTSPLIT_BOT_LINK` on their *first* bill with that person only.
- **Editing or deleting a saved bill:** any participant can, optionally with a reason. The bot shows
  the effect and asks the requester to confirm (§8.4). It is stored as a reversing bill (+ a new bill for
  an edit). Group bills: the change is posted in the group. Personal splits: every participant is
  notified with their new share and the reason. "Last bill" means the speaker's own last bill in this chat.
- **"Not mine":** an edit that removes the speaker from the bill and re-splits their lines among the
  rest; shown and confirmed like any edit.

### 10.6 Payments

- **Recording:** either side can record ("paid Sam 500", "Raj paid me 500"). The bot restates it and
  asks to confirm. Allocation per §9. The other person is notified and can reply "not received", which
  reverses it once they confirm; both are told.
- **Overpaying** (more than A owes B): the restatement shows the extra, recorded as a credit if confirmed.
- **"Undo last payment":** by whoever recorded it, confirmed like any money move; the other person is told.
- **"Square up with Sam":** shows the effect, asks to confirm, writes the square-up settlements (§9); both are told.

### 10.7 Balances, rules, history and privacy

- In a group chat, everything the model sees and the bot says covers only that group (its balances and
  who owes whom, its rules, its bills, its members). Overall balances, other groups, personal splits,
  everywhere rules and history are sent to the asker's personal chat ("sent you a DM"), if they have
  used the bot.
- In a personal chat: overall balances with a per-context breakdown, rules, and history.
- **History:** "what did I spend this month?" = the sum and list of your shares by purchase date;
  "show last 5 bills"; "the Toit bill".

### 10.8 Reminders, notifications, opt-out and delivery

- **Reminders:** manual only. "Remind Raj" sends Raj a friendly nudge with his balance, at most once per
  24 hours per (sender, Raj), and only if he has used the bot and has notifications on.
- **Opt-out:** "stop" turns off notifications and reminders for you; "start" turns them back on.
- **Caps:** at most `SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY` notifications per person per day (a day in
  `SMARTSPLIT_TIMEZONE`); extra ones wait.
- **Tick:** `tick(now)` sends due notifications (rendered with current balances), draft reminders and
  expiries, starts queued drafts behind expired ones, and prunes the transcript. It skips any chat
  whose lock is held (it is tried again next time), so it never waits behind a turn.
- **Delivery:** what one `tick` returns is stored as a `TickBatch`. The gateway acknowledges it after
  sending (`POST /v1/tick/{id}/ack`); a batch not acknowledged within 2 minutes is returned again by the
  next `tick`, with the same id. So a lost response never loses a payment notice; a gateway that
  crashes mid-send may send part of a batch twice.

## 11. Entrypoints

- **CLI** (`smartsplit`): `person add <name> <phone>`, `group create <name>`, `member add <group> <person>`,
  `receipt add <image> --as <person> --in <group | personal>`, `say "<text>" --as <person> --in <group | personal>`,
  `balances --as <person>`, `rules --about <person>`, `tick`, `images prune`. `say` and `receipt add` use
  the real model and need an API key. `smartsplit demo` plays a scripted conversation through the real
  tools and database with no key (`ScriptedAgent`, recorded receipts), to show the flow offline.
  Messages addressed to other people's personal chats are printed with the recipient's name.
- **API** (FastAPI):
  - `POST /v1/messages`: an `InboundMessage` → the replies (§12.2 for status codes);
  - `POST /v1/tick` → `{batch_id, messages}`; `POST /v1/tick/{batch_id}/ack`;
  - operator reads: `GET /v1/groups/{id}/balances`, `GET /v1/people/{id}/balances`, `GET /v1/people/{id}/rules`;
  - `GET /healthz` (the process is up) and `GET /readyz` (the database answers and migrations are at head).
  Every `/v1/*` route requires `Authorization: Bearer <SMARTSPLIT_API_TOKEN>` (constant-time compare);
  the health routes are open. The API needs an API key to start.

## 12. Operations and safety

### 12.1 Configuration

`DATABASE_URL`, `SMARTSPLIT_API_TOKEN`, `ANTHROPIC_API_KEY` (or `SMARTSPLIT_ANTHROPIC_API_KEY`, which wins:
some hosts reserve the plain name), `SMARTSPLIT_CURRENCY`, `SMARTSPLIT_DEFAULT_REGION`, `SMARTSPLIT_TIMEZONE`,
`SMARTSPLIT_BOT_LINK` (a one-tap link to the bot's chat, e.g. `wa.me`, used in invites and "message me 1:1"),
`SMARTSPLIT_IMAGE_DIR`, and with defaults:

| Setting | Default | What |
|---|---|---|
| `SMARTSPLIT_LLM_MODEL` | `claude-haiku-5-5` | chat: the agent loop and canonicalize |
| `SMARTSPLIT_RECEIPT_MODEL` | `claude-sonnet-5-5` | reading receipt photos (§7) |
| `SMARTSPLIT_LLM_TIMEOUT_SECONDS` | 30 | one model call (capped by the time left for the message) |
| `SMARTSPLIT_LLM_MAX_TOKENS` | 16000 | per call (room for a long receipt) |
| `SMARTSPLIT_MESSAGE_SECONDS` | 60 | whole message: photo read, lock wait and agent loop |
| `SMARTSPLIT_LOCK_WAIT_SECONDS` | 15 | waiting for a busy chat before answering 503 |
| `SMARTSPLIT_AGENT_MAX_STEPS` | 6 | model calls per turn |
| `SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY` | 150 | per person who addressed the bot |
| `SMARTSPLIT_LLM_CALLS_PER_DAY` | 3000 | whole install; a warning is logged at 80% |
| `SMARTSPLIT_CHAT_HISTORY_MESSAGES` / `_KEEP` / `_DAYS` | 10 / 50 / 30 | §8.6 |
| `SMARTSPLIT_FUZZY_THRESHOLD`, `SMARTSPLIT_MIN_LINE_CONFIDENCE`, `SMARTSPLIT_MAX_RECEIPT_LINES`, `SMARTSPLIT_MAX_AMOUNT_CENTS`, `SMARTSPLIT_MAX_IMAGE_BYTES`, `SMARTSPLIT_MAX_QUEUED_DRAFTS`, `SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY` | 85, 0.6, 150, 100000000, 5000000, 3, 20 | §6.4, §7, §10 |

Secrets are held as `SecretStr`. The API refuses to start without `SMARTSPLIT_API_TOKEN` and an API key.

### 12.2 The gateway contract and reliability

`POST /v1/messages` answers within `SMARTSPLIT_MESSAGE_SECONDS` plus a few seconds:

| Outcome | Response | Recorded? | Gateway does |
|---|---|---|---|
| Handled (including "nothing to say") | 200 with the replies, possibly none | yes | sends them |
| Same `message_id` again | 200 with the stored replies | — | sends them (it may have lost the first response) |
| Model down, deadline passed, or the turn failed | 200 with one "couldn't do that, try again in a minute" reply | no | sends it; doesn't retry |
| Chat busy longer than `SMARTSPLIT_LOCK_WAIT_SECONDS` | 503 with `Retry-After` | no | retries the same message with backoff |
| Over a daily limit | 200 with one short "limit reached for today" reply (once a day per person) | yes | sends it |
| Bad token / bad request | 401 / 4xx | no | logs it |

The gateway shows "typing…" while a request is in flight, uses an HTTP timeout above
`SMARTSPLIT_MESSAGE_SECONDS`, and retries only on a network error or 503.

- **Idempotency:** each inbound `message_id` is processed once (`ProcessedMessage`), in the same
  transaction as its effects.
- **Serialization:** messages for one chat are handled one at a time (Postgres advisory lock on the
  chat, with a bounded wait). A whole turn is one transaction through the Repository's unit of work, with
  the lock held across its model calls. Each model call's timeout is the smaller of
  `SMARTSPLIT_LLM_TIMEOUT_SECONDS` and the time left. Draft changes are conditional on the expected
  version.
- **Failures inside a turn:** if a model call fails or the deadline passes, the transaction rolls back:
  nothing the turn did is kept and the message isn't recorded. What survives a rollback: the photo read
  (§7) and the usage counts (§12.5). Reaching `SMARTSPLIT_AGENT_MAX_STEPS` is not a failure: the last call
  has no tools, the model says what it did, and the turn commits.
- The database pool has at least as many connections as the API has workers, and idle-in-transaction
  timeouts are longer than `SMARTSPLIT_MESSAGE_SECONDS`.

### 12.3 LLM safety

- The model acts only through tools; every tool checks permissions for the *speaker of this turn*, and
  takes people and things only as handles issued for this turn (§8.2). Raw ids or numbers are rejected.
- Money and other people's data change only through the confirmations of §8.4.
- Untrusted text (chat messages, the transcript, profile names, receipt text, tool results that echo it)
  is passed to the model as data inside tags, never as instructions; the system prompt says so.
- Amounts and balances the user reads are rendered by code (§8.5).

### 12.4 Data and logging

- Logs never contain message bodies, images, prompts or full phone numbers.
- One log line per turn, for debugging without content: a hash of the chat, the outcome (replied,
  silent, failed, deadline, busy), steps, tool names with ok or error, tokens per kind, latency.
- The chat transcript (§8.6) is stored in the database with the limits there, and is part of "forget
  me" (§13).
- Receipt images are stored under `SMARTSPLIT_IMAGE_DIR` (`image_ref` is a file name), with a CLI command
  to prune old ones.
- Request bodies and images are size-limited (`SMARTSPLIT_MAX_IMAGE_BYTES`).

### 12.5 Cost and limits

- The tools and system prompt are fixed and come first, so they are the cached prefix (5-minute cache);
  the per-turn input and the loop's steps follow it.
- Every model call (loop steps, photo reads, canonicalize) is counted in its own short transaction, so
  failed turns count too: against the install's daily total always, and against the speaker's daily
  limit when they addressed the bot (a person isn't charged for group messages the bot only checked).
  Over either limit the bot says so once, without calling the model, until tomorrow (install timezone).
- Models are split by job: chat on Claude Haiku 5.5, receipt photos on Claude Sonnet 5.5 (a misread
  goes straight into the numbers). Expected: 2–4 model calls for a typical message (one for "yes"),
  well under $0.01 per message with the cache warm, plus one Sonnet vision call per receipt. Each call logs its token
  usage (counts only); the live tests print a usage table with the cost.

### 12.6 Deploying and running it

- A container image for the API (and CLI), and a `docker-compose.yml` with Postgres (bound to
  `127.0.0.1`) and the app. Migrations run at start, under a lock.
- `tick` must run every minute (a compose service with a loop, a cron line or a systemd timer, in the
  README); without it, notifications aren't sent and drafts never expire.
- Backups: `pg_dump` of the database plus the image directory; the ledger is the source of truth. The
  README gives the commands and a restore check.

## 13. Future (design for it, don't build it)

- The WhatsApp gateway is a separate small Node service using Baileys, built against §12.2: it turns
  WhatsApp events into `POST /v1/messages` (with mentions, quoted text, `bot_added` and
  `participant_left`), shows "typing…", calls `POST /v1/tick` every minute and acknowledges each batch,
  and sends the replies. The bot runs on a dedicated number, never a personal one.
- **Forget me:** an operator CLI command and a chat command that delete a person's identities, nicknames,
  rules (about or by them), their chat messages and images, and replace their name and phone with "Former member", keeping
  ledger rows so other people's balances stay correct.
- A Splitwise sync adapter would mirror confirmed `Bill`s out.
- Payment links: UPI and Venmo deep links in balance replies; reading a payment screenshot as a payment.
- Item categories ("no alcohol" covers beer and wine).
- Automatic reminders and a weekly summary.
- Currency conversion.
- Asking a person to confirm a learned rule as their own `Everywhere` rule.
