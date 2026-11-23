# SmartSplit — Specification

SmartSplit is a self-hostable, open-source expense splitter for shared houses,
trips and friends. You snap a receipt, and it splits each line item between the
right people, using what it remembers about who uses what ("don't add milk to
Raj", "Sam usually doesn't eat chips"). It asks when unsure, keeps its own
ledger, and talks to people in group chats and in personal (1:1) chats. Later
that chat is WhatsApp; in this build it is a CLI and an HTTP API.

This document is the source of truth. If the code and this spec disagree, the
spec wins, unless DECISIONS.md records a change. `docs/USE_CASES.md` lists the
user-facing situations this spec must cover.

---

## 1. Scope of this build (the first run)

**In scope:** the core, end to end, with no WhatsApp:

1. Domain model and Postgres persistence
2. Split engine (pure, deterministic), including weighted shares and per-item tax
3. People and identity: phone numbers, chat identities, per-user nicknames
4. Two kinds of bill context: **group** bills and **personal splits** (added in a 1:1 chat with chosen people)
5. Preference rules with scopes (everywhere, group, adder's notes), item matching and learning
6. Receipt parsing from an image (Claude vision, behind an interface)
7. Natural-language commands → structured actions (Claude, behind an interface)
8. Ledger: balances per context, overall balances across contexts, debt simplification, settle-up with allocation
9. Conversation orchestrator: bill flow, questions, confirm, cancel, edit/undo, disputes, notifications, membership changes, manual reminders, history
10. A CLI channel and a FastAPI HTTP API that drive the orchestrator, plus a `tick` entrypoint for timed work

**Out of scope (do not build):** the WhatsApp/Baileys gateway, the Splitwise
sync adapter, payment links, currency conversion, item categories, automatic
reminders, auth/multi-tenant hosting, and a web UI. Design for them through the
interfaces below, but write no code for them (see §13).

---

## 2. Architecture

Layered, with dependencies only pointing downward. `scripts/check.sh` enforces
this with import-linter, so a violation fails the build.

```
smartsplit/
  domain/        pure dataclasses, enums, money helpers. Imports nothing from smartsplit.
  engine/        split engine, per-item tax folding, rule resolution. Pure. Imports only domain.
  ledger/        balances, debt simplification, settlement allocation. Pure. Imports only domain.
  ports/         Protocol interfaces: ReceiptParser, CommandInterpreter, Repository, Clock, IdGenerator.
  services/      orchestrator + use-cases. Imports domain, engine, ledger, ports. Never adapters.
  adapters/
    db/          SQLAlchemy models, repositories, Alembic migrations (implements ports.Repository)
    llm/         Anthropic-backed ReceiptParser + CommandInterpreter (implements ports)
    fakes/       in-memory/fake implementations of every port, used by tests and the CLI demo
  entrypoints/
    api/         FastAPI app (webhook-style inbound messages + REST reads + tick)
    cli/         Typer CLI channel
  config.py      settings from env (pydantic-settings)
```

Rules:
- `domain`, `engine` and `ledger` are pure: no I/O, no clock, no randomness, no logging side effects.
- Only `adapters/llm` imports `anthropic`. Only `adapters/db` imports `sqlalchemy`.
- `services` depends on ports (Protocols), and gets concrete adapters injected at the entrypoint.
- Wiring happens in one composition root per entrypoint.
- Services never send messages themselves. Every use-case returns the `OutboundMessage`s it
  wants delivered (to the current chat or to other people's personal chats); the entrypoint
  hands them to the caller. So there is no Channel port.

## 3. Conventions

- **Money is integer cents** (`int`) everywhere. Never `float`. Use `fractions.Fraction` internally where exact division matters.
- **One currency per install**, set in config (`SMARTSPLIT_CURRENCY`, ISO code). No group, person or receipt has its own currency. No FX.
- **Phone numbers** are stored in E.164 (`+919876543210`). Numbers without a country code get `SMARTSPLIT_DEFAULT_COUNTRY_CODE` from config.
- IDs are strings (UUID4 hex) from the `IdGenerator` port, never generated in pure layers.
- Time comes from the `Clock` port.
- Python 3.12+, full type hints, `mypy --strict` clean.
- Files stay under ~300 lines. Functions stay short and single-purpose.

---

## 4. Domain model

### 4.1 People

| Entity | Key fields | Notes |
|---|---|---|
| `Person` | id, display_name, phone, created_at | `phone` is required and unique: it is the person's identity. `display_name` is their own name (from their chat profile once they use the bot, else the name they were first added under). |
| `ChatIdentity` | channel, external_ref, person_id | How a person appears in one channel (`whatsapp` number, `whatsapp_lid`, `cli` handle). `(channel, external_ref)` is unique and maps to exactly one person. |
| `Nickname` | owner_id, subject_id, name | What one person calls another ("Sam" for you, "Samuel" for Raj). Unique per (owner, normalized name). |

### 4.2 Where bills live

| Entity | Key fields | Notes |
|---|---|---|
| `Group` | id, name, channel_ref (optional, unique) | `channel_ref` links the group to one group chat. |
| `Membership` | group_id, person_id, position, joined_at, left_at (optional) | `position` orders members (rounding ties). A member is *active* while `left_at` is empty. A person can rejoin with a new membership. |
| `Context` | `GroupContext(group_id)` \| `PersonalContext()` | Every bill, receipt, draft and settlement row has exactly one context. A personal split has no group; its people are the bill's participants. |
| `Conversation` | channel, ref, kind (`group` \| `personal`), group_id or person_id | One chat the bot is in. A person "has used the bot" once they have a personal conversation. |

### 4.3 Items and rules

| Entity | Key fields | Notes |
|---|---|---|
| `Item` | key, aliases | Install-wide catalogue of item keys (`"milk"`), shared by every context so rules match everywhere. `aliases` are normalized raw names already mapped to this key (the canonicalization cache). |
| `Rule` | id, subject_id, item_key, kind, scope, author_id, source, created_at | `kind`: `exclude` \| `soft_exclude` \| `only`. `scope`: `Everywhere` \| `GroupScope(group_id)` \| `NotesScope(owner_id)`. `source`: `stated` \| `learned`. At most one rule per (scope, subject, item_key). |

### 4.4 Receipts and bills

| Entity | Key fields | Notes |
|---|---|---|
| `Receipt` | id, context, payer_id, merchant, purchased_at, line_items, tax_cents, other_adjustments_cents, total_cents, image_ref, warnings | `other_adjustments_cents` = tip + service charges − receipt-level discounts. |
| `LineItem` | id, name, quantity, amount_cents, taxed, confidence, canonical | `amount_cents` is the line total (may be negative for discount lines). `quantity` ≥ 1 (default 1). `taxed`: `True`/`False` when the receipt marks it, `None` when it doesn't say. `confidence` 0–1 from the parser. `canonical`: optional item key. |
| `Bill` | id, context, receipt_id (optional), payer_id, added_by, description, participants (ordered), total_cents, shares {person_id: cents}, reverses_id (optional), created_at | Append-only. A correction is a reversing bill (negated shares, `reverses_id` set) plus, for an edit, a new bill. Shares sum exactly to `total_cents`. |
| `Dispute` | id, bill_id, person_id, reason, status (`open` \| `resolved`), created_at | A bill is *disputed* while it has an open dispute. It still counts in balances. |
| `Settlement` | id, payment_id, context, from_id, to_id, amount_cents, created_at | One real payment is stored as one row per context it was allocated to, sharing `payment_id`. |

### 4.5 Conversation state

| Entity | Key fields | Notes |
|---|---|---|
| `BillDraft` | id, conversation_ref, context, added_by, payer_id, receipt_id or manual details, participants, overrides, state, created_at, updated_at, reminded_at | A bill under review. `overrides`: item_id → list of people or {person: weight}. At most one draft per conversation is active; later receipts wait as `queued` drafts. |
| `PendingQuestion` | id, draft_id, item_id, member_id (optional), reason, status (`open` \| `answered`), answers [(person_id, answer)] | |
| `Notification` | id, person_id, text, created_at, sent_at (optional) | Outbox for messages to people's personal chats. Flushed (and batched per person) by `tick`. |

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
   (one question per member and item, however many matching rules).
5. If the result is empty → assign to all members and emit `Question(item_id, None, NO_ELIGIBLE_MEMBERS)`.

Rules whose `member_id` is not in `members` are ignored.

Then compute amounts:
- Each item is split among its assignees in proportion to their weights (1 each unless an override gives weights), using exact `Fraction`s.
- `adjustments_cents` is allocated in proportion to each member's item subtotal, with negative subtotals counted as 0.
  If the raw subtotals sum to 0 or less, or every clamped subtotal is 0 (for example no items, or a discount cancelling everything out), it is split equally.
- **Rounding:** floor each member's exact total share (items + adjustments), then hand the leftover cents one at a time to the members with the largest fractional remainders. Break ties by member order. The same rule applies to negative shares.
- Result: `shares` has every member (0 allowed) and sums **exactly** to `sum(items) + adjustments_cents`.

Validation (`ValueError`): an empty or duplicate member list; duplicate item ids; an override
for an item id not in `items`; an empty override; an override naming a non-member; an override
weight that is not a positive integer.

Contract change (approved by the user, see DECISIONS.md): `overrides` accepts
`Mapping[str, Sequence[str] | Mapping[str, int]]`. A list keeps the original equal-split
behaviour, so the original acceptance tests are unchanged.

### 5.1 Per-item tax (pure, in `engine`)

Before splitting, `fold_item_tax(items, tax_cents)` decides where the receipt's tax goes:
- If at least one line has `taxed=True` and the taxed lines sum to more than 0, the tax is
  spread over the taxed lines only, in proportion to their amounts (same floor + largest-remainder
  rounding, ties by line order), and added into those lines' amounts. It returns the new lines and
  0 tax left over.
- Otherwise it returns the lines unchanged and the whole `tax_cents` left over.

The orchestrator then calls `split_receipt` with the folded lines and
`adjustments_cents = leftover tax + other_adjustments_cents`.

---

## 6. People, rules and matching

### 6.1 Identity

- A person is identified by phone number; there are no name-only people. Adding someone the bot
  doesn't know needs their contact card or number.
- Inbound messages are resolved to a person through `ChatIdentity`. The first message from an
  unknown identity creates the person (name from the chat profile).
- Names in commands ("split with Sam") resolve, for the speaker, in this order: their nicknames,
  then display names of people they share an active group or a past bill with. Several matches →
  the bot asks which one. No match → the bot asks for a contact card or number.

### 6.2 Rule scopes and who may change them

| Scope | Created by | Applies to | Who may delete |
|---|---|---|---|
| `Everywhere` | the subject, stating it about themselves in their personal chat | every bill they're in | only the subject |
| `GroupScope(g)` | anyone stating it in group g's chat, or learned from answers in g | bills in group g | any active member of g (the subject is told) |
| `NotesScope(owner)` | the owner, stating it about someone in their personal chat, or learned from the owner's answers there | personal splits the owner adds | only the owner |

- A statement about yourself made in a group chat is a group rule, not an everywhere rule.
- A new stated rule replaces any rule for the same (scope, subject, item key). A learned rule never replaces a stated one.
- When a member's membership ends, that group's rules about them stop applying (they are kept, and apply again if they rejoin).
- Anyone can ask "what rules are about me?" and gets every rule with them as subject, including scope and author.

### 6.3 Resolving the rules for one bill (pure, in `engine`)

`resolve_rules(rules, participants, context, added_by)` returns one rule per (participant, item key):
1. Candidates: rules whose subject is a participant, and whose scope is `Everywhere`,
   or `GroupScope` of this bill's group, or `NotesScope(added_by)` for a personal split.
2. If several candidates share (subject, item key), the most specific scope wins
   (`GroupScope`/`NotesScope` over `Everywhere`), then `stated` over `learned`, then the newest.

### 6.4 Canonicalization

Receipt names are messy (`"2% MLK GAL"`). `canonicalize(name, known_keys)` maps a raw name to an
existing item key or proposes a new one:
1. exact match on the normalized name or a stored alias
2. deterministic fuzzy match (token overlap / rapidfuzz ratio ≥ threshold, set in config)
3. otherwise ask the LLM `CommandInterpreter.canonicalize` (behind the port). The result is stored as an alias on the install-wide `Item` catalogue.

### 6.5 Learning

When answers for the same (subject, item key) go the same way twice in the same scope, with no
contradicting answer in between, create a `learned` rule (`exclude` or `only`) in that scope:
answers in a group chat → `GroupScope`; answers in a personal chat → `NotesScope(adder)`.
`Everywhere` rules are never learned.

---

## 7. Receipt parsing

- Port: `ReceiptParser.parse(image_bytes, mime_type, currency) -> ParsedReceipt`, where `currency` is the install currency.
- Anthropic adapter: one vision call with a strict JSON schema (use tool-use / structured output), model from config. Retries once on invalid JSON. Returns line items in integer cents with quantity, `taxed` (true/false/unknown) and a `confidence` per item, plus tax, other adjustments and total.
- If the invariant in §4 fails, `ParsedReceipt.warnings` says so, and the orchestrator asks the user to confirm the total.
- Lines with confidence below `SMARTSPLIT_MIN_LINE_CONFIDENCE` (config) are flagged in the summary ("couldn't read line 4 clearly: SPRT DRNK ₹120?") and must be confirmed or fixed before the bill can be saved.
- A receipt in a different currency from the install's gets a warning; nothing is converted.
- Tests use recorded fixtures (`tests/fixtures/receipts/*.json`). No network in tests. One opt-in live test runs only when `SMARTSPLIT_LIVE_LLM=1`.

## 8. Natural-language commands

Port: `CommandInterpreter.interpret(text, context) -> Command`, where `context` carries the
conversation kind, the speaker, the people they can name (with nicknames), open questions and the
active draft. `Command` is a tagged union:

| Area | Commands |
|---|---|
| Bills | `StartSplit` (who it's with, payer, "X owes all"), `AddManualBill`, `AnswerQuestion`, `EditDraft`, `ConfirmDraft`, `CancelDraft`, `EditBill`, `DeleteBill`, `DisputeBill`, `ShowBillDetails` |
| People and groups | `AddPerson` (name + number or contact card), `AddMember`, `MemberLeft`, `SetNickname` |
| Rules | `AddRule`, `DeleteRule`, `ListRules` (about someone, or "about me") |
| Money | `ShowBalances` (overall, with someone, or in a group), `SettleUp` (with someone, optionally one context), `Remind`, `ShowHistory` |
| Other | `Help`, `Unknown` |

The Anthropic adapter uses tool-use, with one tool per command. The fake adapter uses simple
keyword/regex patterns, good enough for tests and the CLI demo. Contact cards arrive as structured
attachments on the inbound message, not as text.

## 9. Ledger

All pure, in `ledger`.

- **Pairwise debts per context:** for each bill, each participant other than the payer owes the
  payer their share; settlements reduce the debt from `from_id` to `to_id`. Netted per pair of
  people per context. Reversing bills cancel the originals. Disputed bills count.
- **Group balance** per member = paid − owed within that group. Always sums to 0 per group.
- **Overall balance** between two people = the sum of their pairwise debts over all contexts, with
  a breakdown per context (each group, plus "personal splits").
- `simplify_debts(balances) -> list[Transfer]` gives the minimal-count greedy settlement for one
  group (largest creditor ↔ largest debtor). It's deterministic, with ties broken by member order.
  The overall view never moves debts between contexts.
- **Settle-up allocation:** a payment from A to B without a named context is allocated to the
  contexts where A owes B, largest debt first, ties broken by the context's oldest unsettled bill.
  Any amount above what A owes B is recorded in the personal-splits context (B now owes A).
  A payment for a named context goes entirely to that context.
- Bills and settlements are append-only. Corrections are new reversing entries, never edits.

## 10. Orchestrator

A channel-agnostic state machine in `services/`. State lives in the DB, so a restart mid-flow
resumes cleanly. Every state transition is covered by an integration test using fakes.

### 10.1 Messages

- Inbound: `InboundMessage(channel, conversation_ref, conversation_kind, sender_ref, sender_name, text | image | contact)`.
- Outbound: `OutboundMessage(conversation_ref, text)`. Plain text that reads well in a chat app: short lines, no markdown tables.
  Replies go to the current conversation; notifications go to a person's personal conversation.

### 10.2 Onboarding

- **First personal message** from an unknown identity: create the person, reply with a short welcome and help.
- **First message in an unknown group chat:** create the group linked to that chat, and add the sender as a member.
  Anyone who later writes in the chat becomes a member. "Add Priya" (contact card or number) adds quiet members.

### 10.3 Bill flow

```
receipt or manual bill → (group: participants = active members;
                          personal: participants = speaker + people named, asked if missing)
  → parse → canonicalize items → fold tax → resolve rules → split_receipt
  → no questions: send the summary, wait for confirm / edit / cancel
  → questions: ask them (batch if ≤3), collect answers as overrides → re-split
  → confirm by the adder → write Bill → learn from answers → notify → reply with new balances
```

- **Summary:** each person's share, who was skipped and why, flagged low-confidence lines and total
  warnings. The reason is shown for group rules and the adder's own notes; for someone's `Everywhere`
  rule, the summary only says they were skipped, so personal facts don't leak into other groups.
- **Filing into a group from a personal chat:** "add to Flat 4B" turns the draft into a bill in that
  group (the speaker must be an active member); participants become the group's active members and the
  saved summary is posted in the group chat.
- **One draft per conversation.** A new receipt while a draft is open is queued: "I'll do this one after we finish the Toit bill."
- **Answers:** anyone in the bill's context may answer. If two people answer the same question
  differently, the bot asks again and shows both answers. Only the adder confirms.
- **Cancel:** drops the draft. Nothing is saved.
- **Unanswered:** if a draft has had no activity for 24 hours, the adder gets one reminder (via `tick`). Nothing is saved until confirmed.

### 10.4 After saving

- **Personal splits — notifications:** every participant who has used the bot gets a personal message
  with the bill, their share and their new overall balance with the adder, and can reply `ok`, `details`
  or `dispute`. Several bills to the same person within one `tick` interval are batched into one message.
  Participants who have never used the bot are not messaged; the adder gets a forwardable invite text
  instead (link template from config). On their first message, newcomers see what is waiting for them.
- **Group bills:** the summary is posted in the group chat; no personal messages.
- **Disputes:** the disputer is asked what's wrong, the adder is told, and the bill is flagged until the
  adder edits it or resolves the dispute.
- **Edit / delete:** any participant can ask; the bot shows the change and asks to confirm; it is stored
  as a reversing bill (+ new bill for an edit); all participants are told their new share.

### 10.5 Membership, reminders, history

- **Moving out** (`MemberLeft`): the membership ends; they're not in new bills; their balance stays until settled and they can still see it.
- **Moving in** (`AddMember`): membership starts now; only bills from then on include them.
- **Reminders:** manual only. "Remind Raj" sends Raj a friendly nudge with his balance, if he has used the bot.
- **History:** read-only: "what did I spend this month?", "show last 5 bills".

### 10.6 Tick

`tick(now)` runs timed work: draft reminders after 24 hours of inactivity, and flushing batched
notifications. Entrypoints expose it so the host can run it every few minutes.

## 11. Entrypoints

- **CLI** (`smartsplit`): `person add <name> <phone>`, `group create <name>`, `member add <group> <person>`,
  `receipt add <image> --as <person> --in <group | personal>`, `say "<text>" --as <person> --in <group | personal>`,
  `balances --as <person>`, `rules --about <person>`, `tick`. Use it to demo the full flow with the fake or the real LLM adapters (`--live`).
  Messages addressed to other people's personal chats are printed with the recipient's name.
- **API** (FastAPI): `POST /v1/messages` (an `InboundMessage` JSON → list of `OutboundMessage`),
  `POST /v1/tick` (→ list of `OutboundMessage`), `GET /v1/groups/{id}/balances`, `GET /v1/people/{id}/balances`,
  `GET /v1/people/{id}/rules`, `GET /healthz`. `POST /v1/messages` is the endpoint the future WhatsApp gateway will call.

## 12. Configuration

`DATABASE_URL`, `SMARTSPLIT_CURRENCY`, `SMARTSPLIT_DEFAULT_COUNTRY_CODE`, `SMARTSPLIT_LLM_MODEL`,
`ANTHROPIC_API_KEY` (only for live runs), `SMARTSPLIT_FUZZY_THRESHOLD`, `SMARTSPLIT_MIN_LINE_CONFIDENCE`,
`SMARTSPLIT_INVITE_TEMPLATE` (the forwardable invite text, e.g. containing a `wa.me` link).

## 13. Future (design for it, don't build it)

- The WhatsApp gateway is a separate small Node service using Baileys. It turns WhatsApp events into `POST /v1/messages`, calls `POST /v1/tick` on a timer, and sends the replies. The bot runs on a dedicated number, never a personal one.
- A Splitwise sync adapter would mirror confirmed `Bill`s out.
- Payment links: UPI and Venmo deep links in balance replies.
- Item categories ("no alcohol" covers beer and wine).
- Automatic reminders and a weekly summary.
- Currency conversion.
- Asking a person to confirm a learned rule as their own `Everywhere` rule.
