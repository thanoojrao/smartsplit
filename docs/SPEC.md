# SmartSplit — Specification

SmartSplit is a self-hostable, open-source expense splitter for shared houses,
trips and friends. You snap a receipt, and it splits each line item between the
right people, using what it remembers about who uses what ("don't add milk to
Raj", "Sam usually doesn't eat chips"). It asks when unsure, keeps its own
ledger, and talks to people in group chats and in personal (1:1) chats. Later
that chat is WhatsApp; in this build it is a CLI and an HTTP API.

This document is the source of truth. If the code and this spec disagree, the
spec wins, unless DECISIONS.md records a change. `docs/USE_CASES.md` lists the
user-facing situations this spec must cover; `docs/DESIGN_REVIEW.md` records how
the pre-build review shaped it.

---

## 1. Scope of this build (the first run)

**In scope:** the core, end to end, with no WhatsApp:

1. Domain model and Postgres persistence
2. Split engine (pure, deterministic): weighted and exact-amount shares, per-item tax
3. People and identity: phone numbers, chat identities, per-user nicknames
4. Two kinds of bill context: **group** bills (all or some current members) and **personal splits** (added in a 1:1 chat with chosen people)
5. Preference rules with scopes (everywhere, group, adder's notes), item matching and learning
6. Receipt parsing from an image (Claude vision, behind an interface)
7. Natural-language commands → structured actions (Claude, behind an interface)
8. Ledger: balances per context, overall balances across contexts, debt simplification, payments with allocation, square-up
9. Conversation orchestrator: bill flow, questions, review edits, confirm, cancel, expiry, editing saved bills, notifications, membership, payments, reminders, history, opt-out
10. A CLI channel and a FastAPI HTTP API that drive the orchestrator, plus a `tick` entrypoint for timed work
11. Basic safety for a self-hosted service: a shared API token, idempotent message handling, per-conversation serialization

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
  ports/         Protocol interfaces: ReceiptParser, CommandInterpreter, Repository (with unit of work), ImageStore, Clock, IdGenerator.
  services/      orchestrator + use-cases. Imports domain, engine, ledger, ports. Never adapters.
  adapters/
    db/          SQLAlchemy models, repositories, Alembic migrations (implements ports.Repository)
    llm/         Anthropic-backed ReceiptParser + CommandInterpreter (implements ports)
    files/       filesystem ImageStore (implements ports.ImageStore)
    fakes/       in-memory/fake implementations of every port, used by tests and the CLI demo
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
- Services never send messages themselves. `handle` and `tick` return the `OutboundMessage`s to deliver,
  to any conversation (the current chat, a group chat, a personal chat). Messages to people's personal
  chats that are subject to opt-out, caps and holds go through the `Notification` outbox (§10.8). So there
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
| `Nickname` | owner_id, subject_id, name | What one person calls another ("Sam" for you, "Samuel" for Raj). Unique per (owner, normalized name). Others only ever see the name *they* gave someone, never the stored display name of a person they share no context with. |

### 4.2 Where bills live

| Entity | Key fields | Notes |
|---|---|---|
| `Group` | id, name, channel_ref (optional, unique) | `channel_ref` links the group to one group chat. |
| `Membership` | group_id, person_id, position, joined_at, left_at (optional) | `position` orders members (rounding ties). *Current* while `left_at` is empty. Rejoining creates a new membership. |
| `Context` | `GroupContext(group_id)` \| `PersonalContext()` | Every bill, receipt, draft and settlement has exactly one context. A personal split has no group; its people are the bill's participants. |
| `Conversation` | key (channel, ref), kind (`group` \| `personal`), name, group_id or person_id, last_listed_bill_ids | One chat the bot is in. `last_listed_bill_ids` resolves "details 2" against the numbered list last shown there. |

### 4.3 Items, matching and rules

| Entity | Key fields | Notes |
|---|---|---|
| `Item` | key | Install-wide set of item keys (`"milk"`), so rules about an item apply everywhere. |
| `ItemAlias` | match_scope, raw_name, item_key | Remembered match from a normalized receipt name to an item key. `match_scope` is `GroupScope(group_id)` or `NotesScope(owner_id)` (personal splits by that adder), so a wrong match only affects that place. |
| `Rule` | id, subject_id, item_key, kind, scope, author_id, source, created_at | `kind`: `exclude` \| `soft_exclude` \| `only`. `scope`: `Everywhere` \| `GroupScope(group_id)` \| `NotesScope(owner_id)`. `source`: `stated` \| `learned`. At most one rule per (scope, subject, item_key). |
| `LlmUsage` | person_id, day, calls | Counts model calls per person per day (`SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY`). |
| `AnswerObservation` | scope, subject_id, item_key, outcome (`excluded` \| `sole_assignee` \| `included`), bill_id, observed_at | What a saved bill's answers showed about one person and one item; the input to learning (§6.5). |

### 4.4 Receipts, bills and payments

| Entity | Key fields | Notes |
|---|---|---|
| `Receipt` | id, image_ref, mime_type, merchant, purchased_at, line_items, tax_cents, other_adjustments_cents, total_cents, warnings | The immutable parse record. `other_adjustments_cents` = tip + service charges − receipt-level discounts. Review edits happen on the draft's working copy. |
| `LineItem` | id, position, name, quantity, amount_cents, taxed, confidence, canonical, discount_for, match_how, match_is_new | `amount_cents` is the line total (negative for discount/refund lines). `quantity` ≥ 1. `taxed`: `True`/`False`/`None` (receipt doesn't say). `confidence` 0–1. `canonical`: item key. `discount_for`: id of the line this discount reduces, if the parser could link it. `match_is_new` marks a first-time item match (shown once in the summary). |
| `Bill` | id, context, origin conversation, receipt_id (optional), payer_id, added_by, description, purchased_at, participants (ordered), lines, tax_cents, other_adjustments_cents, total_cents, shares, reverses_id (optional), replaces_id (optional), edit_reason (optional), created_at | Append-only. An edit is a reversing bill (`reverses_id`) plus a new bill (`replaces_id`, `edit_reason`); a delete is only the reversing bill. Shares sum exactly to `total_cents`. |
| `BillLine` | id, position, name, item_key, quantity, amount_cents (before tax folding), taxed, discount_for, assignees (person → weight) | The per-line split as saved; with the bill's tax and adjustments, "details" and edits can be rebuilt without re-running rules. |
| `Settlement` | id, payment_id, context, from_id, to_id, amount_cents, kind (`payment` \| `square_up`), recorded_by, reverses_id (optional), created_at | One real payment is stored as one row per context it was allocated to, sharing `payment_id`. Reversal ("not received", "undo") writes negating rows. |

### 4.5 Conversation state

| Entity | Key fields | Notes |
|---|---|---|
| `BillDraft` | id, conversation, context, added_by, payer_id, receipt_id, image_ref, description, purchased_at, working copy of lines / tax / other adjustments / total, accepted_difference_cents, participants, overrides, owes_all_id, state, created_at, last_activity_at, reminded_at | A bill under review; review edits change the working copy. `overrides`: line id → list of people, or {person: weight}, or exact amounts (§5.2). States in §10.4. At most one draft per conversation is active; up to `SMARTSPLIT_MAX_QUEUED_DRAFTS` wait as `queued`. |
| `Prompt` | id, conversation, draft_id (optional), kind, typed payload, status (`pending` \| `open` \| `answered` \| `dropped`), asked_of (optional: only that person may answer), created_by, created_at, answers | Anything the bot is waiting for a reply to, so a restart resumes cleanly. Kinds: `engine_question` (item + member + reason), `who_with`, `which_person`, `need_contact`, `confirm_total`, `confirm_line`, `confirm_action` (edit, delete, payment, overpayment, square-up, rule change), `join_group`, `duplicate_warning`. A `confirm_action` stores the command and its exact effect; "yes" applies that effect only if the data hasn't changed since, otherwise it is recomputed and asked again. |
| `Notification` | id, recipient_id, actor_id, kind, bill_ids, payment_id, args, created_at, sent_at (optional) | Outbox for messages to people's personal chats. Text is rendered when sent (so balances are current). Held while the person hasn't used the bot or has notifications off, except `requested_reply` (answers the person asked for, e.g. "sent you a DM"). |
| `ProcessedMessage` | conversation, message_id, replies, processed_at | Idempotency: a repeated inbound `message_id` returns the stored replies and changes nothing. |

Receipt invariant: `sum(line_items.amount_cents) + tax_cents + other_adjustments_cents == total_cents`.
The parser must flag a receipt where this doesn't hold (in `warnings`), not silently fix it.

---

## 5. Split engine contract (FROZEN)

`smartsplit.engine.split_receipt(...)`. The signature and types live in
`src/smartsplit/engine/__init__.py`. `tests/acceptance/test_split_engine.py`
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

`amounts_to_weights(line_cents, fixed: Mapping[str, int], others: Sequence[str]) -> Mapping[str, int]`
turns "Sam's part was ₹100" into a weighted override: fixed people get exactly their amount, and
the remainder is split equally among `others` (in order). Fixed amounts must be positive and sum to
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
- Names in commands ("split with Sam") resolve, for the speaker, in this order: their nicknames,
  then the names of people they share a current group or a past bill with. Several matches →
  the bot asks which one. No match → the bot asks for a contact card or number.
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
matcher in `engine` and the `CommandInterpreter.canonicalize` port:
1. exact match on the normalized name, or a stored `ItemAlias` in this bill's match scope
   (the group, or the adder's personal splits)
2. deterministic fuzzy match against known item keys (rapidfuzz ratio ≥ `SMARTSPLIT_FUZZY_THRESHOLD`)
3. otherwise ask the LLM `canonicalize(name, known_keys)`.

A match from step 2 or 3 is stored as an `ItemAlias` in that match scope and shown in the summary the
first time ("OAT MLK → milk?"). "That's not milk" removes the alias in that scope, and the line's key
becomes its own normalized name (or the item the speaker names instead).
A discount line linked by the parser (`discount_for`) gets the key of the line it reduces, so it is
shared by the same people, and follows that line's answers and edits unless it has its own; unlinked
discounts are shared by everyone.

### 6.5 Learning

When a bill is saved, each answer to an `engine_question` (and each review edit of who shares a
line) is recorded as an `AnswerObservation` per person and item key, in the bill's rule scope
(group chat → `GroupScope`; personal chat → `NotesScope(adder)`):
- the person was removed from the line → `excluded`
- the person was the only assignee → `sole_assignee`
- otherwise → `included`

When the last two observations for a (scope, subject, item key) are both `excluded`, create or
replace a learned `exclude` rule; both `sole_assignee` → learned `only`. An `included` observation
breaks the streak. `Everywhere` rules are never learned. Weighted splits count as `included`.

---

## 7. Receipt parsing

- Port: `ReceiptParser.parse(image_bytes, mime_type, currency) -> ParsedReceipt`, where `currency` is the install currency.
- Anthropic adapter: one vision call returning structured output against a strict schema, model from
  config (check the current API docs for how structured output / tool use works on the configured
  model before building). Retries once on invalid output or an API error, with a timeout from config.
- Returns line items in integer cents with quantity, `taxed` (true/false/unknown), `discount_for`
  and a `confidence` per item, plus purchase date, tax, other adjustments and total.
- Output is validated into domain types: integer cents, quantity ≥ 1, confidence clamped to 0–1,
  at most `SMARTSPLIT_MAX_RECEIPT_LINES` lines, total > 0. Invalid output → "couldn't read that receipt, try another photo".
- If the invariant in §4 fails, `ParsedReceipt.warnings` says so.
- A receipt in a different currency from the install's gets a warning; nothing is converted.
- Receipt text is untrusted data: it is never treated as instructions (§12.3).
- Tests use recorded fixtures (`tests/fixtures/receipts/*.json`). No network in tests. One opt-in live test runs only when `SMARTSPLIT_LIVE_LLM=1`.

## 8. Natural-language commands

Port: `CommandInterpreter.interpret(text, context) -> Command` and
`CommandInterpreter.canonicalize(name, known_keys) -> str`. `context` carries the conversation kind,
the speaker, the people they can name (with nicknames), open prompts and the active draft.
`Command` is a tagged union:

| Area | Commands |
|---|---|
| Bills | `StartSplit` (who it's with: names, "everyone", "everyone except X"; payer; "X owes all"), `AddManualBill` (description, amount, people, optional exact amounts, optional date), `AnswerPrompt`, `EditDraft` (line amount, remove line, add line, fix total, who shares a line, "that's not milk"), `ConfirmDraft`, `CancelDraft`, `FileIntoGroup`, `EditBill` (with optional reason), `DeleteBill`, `NotMine`, `ShowBillDetails` |
| People and groups | `AddPerson` (name + number or contact card), `JoinGroup`, `AddMember`, `MemberLeft`, `SetNickname`, `CorrectNumber` |
| Rules | `AddRule`, `DeleteRule`, `ListRules` (about someone, or "about me") |
| Money | `ShowBalances` (overall, with someone, or in a group), `RecordPayment` (payer or receiver side, optional context), `NotReceived`, `UndoPayment`, `SquareUp`, `Remind`, `ShowHistory` |
| Other | `Notifications` (stop / start), `Help`, `Unknown` |

The Anthropic adapter uses tool use, with one tool per command. The fake adapter uses simple
keyword/regex patterns, good enough for tests and the CLI demo. Contact cards arrive as structured
attachments on the inbound message, not as text. Amounts in commands are validated as positive
integer cents below `SMARTSPLIT_MAX_AMOUNT_CENTS`.

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

A channel-agnostic state machine in `services/`. State lives in the DB, so a restart mid-flow
resumes cleanly. Every state transition is covered by an integration test using fakes.

### 10.1 Messages

- Inbound: `InboundMessage(message_id, channel, conversation_ref, conversation_kind, sender_ref,
  sender_phone (optional), sender_name, addressed_to_bot, reply_to_bot, text | image | contact | event)`.
  `event` covers chat events from the gateway: `participant_left` (with the person's ref).
- Outbound: `OutboundMessage(conversation_ref, text)`. Plain text that reads well in a chat app: short lines, no markdown tables.

### 10.2 When the bot reacts

- **Personal chats:** every message.
- **Group chats:** only photos, messages addressed to the bot (mention or a command word such as
  "split", "paid", "balances"), replies to the bot, and replies that clearly answer one of its open
  prompts. Everything else is ignored silently, and `Unknown` gets no reply in groups.

### 10.3 Onboarding and membership

- **First personal message** from an unknown identity: create the person, reply with a short welcome and help.
  Anything waiting for them (bills they're in, held notifications) is shown.
- **First message to the bot in an unknown group chat:** create the group linked to that chat; the
  sender joins; the bot asks others to reply "join".
- **Joining is explicit:** "join", or a member adds someone ("add Priya" + contact or number). A
  non-member who talks to the bot is asked "join splits here?" (a `join_group` prompt).
- **Leaving:** "X moved out" (by anyone), or a `participant_left` event, ends the membership. People
  who left never rejoin by posting; rejoining is explicit.
- Every membership change is announced in the group. No confirmation is needed.
- A leaver is not in new bills; their balance stays until settled and they can still see it.
  In that group's open drafts they are removed from the participants, their prompts are dropped, and the
  draft is re-split and its summary shown again. If the adder of a draft leaves, the draft is cancelled.

### 10.4 Bill flow

```
receipt or manual bill → choose participants → parse → (duplicate check) → match items → fold tax
  → resolve rules → split_receipt → summary (+ prompts) → [review edits / answers → re-split]*
  → confirm by the adder → write Bill + lines + observations → learn → notify → reply with balances
```

**Participants**
- Group: all current members by default, or a subset named by the adder ("me and Priya",
  "everyone except Raj"). Only current members can be included. Snapshotted when the draft is created.
- Personal: the speaker plus the people named; if none are named, a `who_with` prompt offers a
  numbered list of recent/frequent people and groups.
- **Payer:** in groups, the adder unless they say "Sam paid". In personal splits, always the adder.

**Draft states**

| State | Meaning | Leaves to |
|---|---|---|
| `queued` | waiting behind the active draft in this conversation (parsed only when it starts) | `awaiting_people` / `parsing` when the active draft is saved, cancelled or expired |
| `awaiting_people` | personal split with nobody named yet | `parsing` on an answer |
| `parsing` | receipt being read | `reviewing`; on failure the draft is cancelled with "couldn't read that, try again" |
| `reviewing` | summary shown, prompts may be open, edits allowed | `saved` (adder confirms), `cancelled`, `expired` |
| `saved` / `cancelled` / `expired` | terminal | — |

- **Summary (short):** each person's total, who was skipped and why, first-time item matches, flagged
  low-confidence lines (below `SMARTSPLIT_MIN_LINE_CONFIDENCE`) and total warnings. "details" shows the
  numbered full list; lines can be referred to by number or name. The reason is shown for group rules
  and the adder's own notes; for someone's `Everywhere` rule the summary only says they were skipped.
- **Review edits:** "line 4 is 120", "remove the bag", "add water 40", "total is 1840", "Raj had none
  of the wine", "2 for Sam, 1 for Raj", "that's not milk". After each edit the split is recomputed.
  If lines + tax + adjustments still don't match the total, the summary shows the difference and the
  adder either fixes a line or accepts it as an adjustment shared like tip.
- **Questions:** up to 3 are asked in one message; the rest wait as `pending` prompts and the next batch
  is asked once the current one is answered. Anyone in the bill's
  context may answer. An answer changes the current assignment of that line (other open questions on
  it stay open). If people answer differently, the latest answer wins. The adder can confirm with
  questions still open; the split shown is used.
- **Duplicates:** after parsing, if a saved bill (not reversed) or another open draft in the same group
  (or between the same people) has the same total within 3 days, a `duplicate_warning` asks to continue or cancel.
- **Confirm:** only the adder.
- **Cancel:** any current member (group) or the adder (personal) can cancel at any time; in groups the bot says who cancelled.
- **Reminder and expiry:** after 24 hours without activity one reminder is posted in the draft's chat
  (group chat for group drafts); after 3 days the draft expires with a short message there. Nothing is
  saved until confirmed.
- **Queued drafts** start when the active one is saved, cancelled or expires; their receipt is parsed
  then, outside the conversation lock (§12.2).
- **Filing into a group** ("add to Flat 4B") from a personal chat: the speaker must be a current
  member; the draft's context becomes that group, rules are re-resolved with that group's rules and
  any new questions are asked in the personal chat; the adder confirms there; the saved bill's summary
  is posted in the group. The group's own draft is not affected.

### 10.5 After saving: notifications and edits

- **Group bills:** the summary and new balances are posted in the group chat; no personal messages.
- **Personal splits:** every other participant gets a notification: the bill, their share and their new
  overall balance with the payer. Replies: `ok` (no reply needed), `details`, `not mine`, or an edit. Several bills to one
  person within one `tick` interval become one message with numbered bills ("details 2").
  Participants who have never used the bot are not messaged; the adder gets a forwardable invite text
  (`SMARTSPLIT_INVITE_TEMPLATE`) on their *first* bill with that person only.
- **Editing or deleting a saved bill:** any participant can, optionally with a reason. The bot shows
  the effect and asks the requester to confirm (`confirm_action`). It is stored as a reversing bill
  (+ a new bill for an edit). Group bills: the change is posted in the group. Personal splits: every
  participant is notified with their new share and the reason. "Last bill" means the speaker's own last
  bill in this chat.
- **"Not mine":** an edit that removes the speaker from the bill and re-splits their lines among the
  rest; shown and confirmed like any edit.

### 10.6 Payments

- **Recording:** either side can record ("paid Sam 500", "Raj paid me 500"). The bot restates it and
  asks to confirm. Allocation per §9. The other person is notified and can reply "not received", which
  reverses it (both are told).
- **Overpaying** (more than A owes B): the bot shows it and asks to confirm before recording the extra as a credit.
- **"Undo last payment":** by whoever recorded it; reverses it; the other person is told.
- **"Square up with Sam":** shows the effect, asks to confirm, writes the square-up settlements (§9); both are told.

### 10.7 Balances, rules, history and privacy

- In a group chat, answers only cover that group (its balances and who owes whom, its rules, its
  bills). Overall balances, other groups, personal splits, everywhere rules and history are sent to the
  asker's personal chat ("sent you a DM"), if they have used the bot.
- In a personal chat: overall balances with a per-context breakdown, rules, and history.
- **History:** "what did I spend this month?" = the sum and list of your shares by purchase date;
  "show last 5 bills".

### 10.8 Reminders, notifications and opt-out

- **Reminders:** manual only. "Remind Raj" sends Raj a friendly nudge with his balance, at most once per
  24 hours per (sender, Raj), and only if he has used the bot and has notifications on.
- **Opt-out:** "stop" turns off notifications and reminders for you; "start" turns them back on.
- **Caps:** at most `SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY` notifications per person per day (a day in
  `SMARTSPLIT_TIMEZONE`; `requested_reply` doesn't count); extra ones wait.
- **Delivery:** `tick(now)` claims unsent notifications (`FOR UPDATE SKIP LOCKED`), renders them with
  current balances, marks them sent in the same transaction and returns them (at-most-once delivery).
  It also sends draft reminders and expires drafts.

## 11. Entrypoints

- **CLI** (`smartsplit`): `person add <name> <phone>`, `group create <name>`, `member add <group> <person>`,
  `receipt add <image> --as <person> --in <group | personal>`, `say "<text>" --as <person> --in <group | personal>`,
  `balances --as <person>`, `rules --about <person>`, `tick`. Use it to demo the full flow with the fake or the real LLM adapters (`--live`).
  Messages addressed to other people's personal chats are printed with the recipient's name.
- **API** (FastAPI): `POST /v1/messages` (an `InboundMessage` JSON → list of `OutboundMessage`),
  `POST /v1/tick` (→ list of `OutboundMessage`), `GET /v1/groups/{id}/balances`,
  `GET /v1/people/{id}/balances`, `GET /v1/people/{id}/rules`, `GET /healthz`.
  Every `/v1/*` route requires `Authorization: Bearer <SMARTSPLIT_API_TOKEN>` (constant-time compare);
  `/healthz` is open. The REST reads are for the operator, not end users. `POST /v1/messages` is the
  endpoint the future WhatsApp gateway will call.

## 12. Operations and safety

### 12.1 Configuration

`DATABASE_URL`, `SMARTSPLIT_API_TOKEN`, `SMARTSPLIT_CURRENCY`, `SMARTSPLIT_DEFAULT_REGION`, `SMARTSPLIT_TIMEZONE`,
`SMARTSPLIT_LLM_MODEL`, `SMARTSPLIT_LLM_TIMEOUT_SECONDS`, `SMARTSPLIT_LLM_MAX_TOKENS`, `SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY`,
`ANTHROPIC_API_KEY` (only for live runs), `SMARTSPLIT_FUZZY_THRESHOLD`, `SMARTSPLIT_MIN_LINE_CONFIDENCE`,
`SMARTSPLIT_MAX_RECEIPT_LINES`, `SMARTSPLIT_MAX_AMOUNT_CENTS`, `SMARTSPLIT_MAX_IMAGE_BYTES`, `SMARTSPLIT_MAX_QUEUED_DRAFTS`,
`SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY`, `SMARTSPLIT_INVITE_TEMPLATE` (operator-set text, e.g. a `wa.me` link), `SMARTSPLIT_IMAGE_DIR`.
Secrets are held as `SecretStr`. The API refuses to start without `SMARTSPLIT_API_TOKEN`.

### 12.2 Reliability

- **Idempotency:** each inbound `message_id` is processed once (§4.5 `ProcessedMessage`), in the same transaction as its effects.
- **Serialization:** messages for one conversation are handled one at a time (Postgres advisory lock on the
  conversation ref); each message is one transaction through the Repository's unit of work. Draft state
  changes are conditional on the expected current state.
- **LLM calls** happen before taking the lock and opening the transaction; on timeout or error the bot replies
  "couldn't do that, try again in a minute" and nothing changes. Calls are counted per person per day
  (`LlmUsage`); over the limit the bot says so and waits until tomorrow.

### 12.3 LLM safety

- Model output is only a proposal: services check every permission and resolve people only from the
  speaker's nameable list (ids supplied by the model are rejected).
- Commands that move money, delete or change others' data (payments, square-up, edit/delete bill, delete rule,
  rules about others, membership changes) are restated deterministically and need a "yes", except
  membership changes, which are announced (§10.3).
- Untrusted text (chat messages, profile names, receipt text) is passed to the model as data, never as instructions.

### 12.4 Data and logging

- Logs never contain message bodies, images, prompts or full phone numbers.
- Receipt images are stored under `SMARTSPLIT_IMAGE_DIR` (`image_ref` is a file name), with a CLI command to prune old ones.
- Request bodies and images are size-limited (`SMARTSPLIT_MAX_IMAGE_BYTES`).
- `docker-compose.yml` binds Postgres to `127.0.0.1` only.

## 13. Future (design for it, don't build it)

- The WhatsApp gateway is a separate small Node service using Baileys. It turns WhatsApp events into `POST /v1/messages`, calls `POST /v1/tick` on a timer, and sends the replies. The bot runs on a dedicated number, never a personal one.
- **Forget me:** an operator CLI command and a chat command that delete a person's identities, nicknames,
  rules (about or by them) and images, and replace their name and phone with "Former member", keeping
  ledger rows so other people's balances stay correct.
- A Splitwise sync adapter would mirror confirmed `Bill`s out.
- Payment links: UPI and Venmo deep links in balance replies.
- Item categories ("no alcohol" covers beer and wine).
- Automatic reminders and a weekly summary.
- Currency conversion.
- Asking a person to confirm a learned rule as their own `Everywhere` rule.
