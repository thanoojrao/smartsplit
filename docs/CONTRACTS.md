# SmartSplit — Data shapes and contracts (v3, revision 2 after the product pass)

The concrete types and interfaces every milestone builds against. SPEC.md says *what* happens;
this file says *what the data looks like*. Python-style signatures. Field names are final once
agreed; changing them later is a decision to log in DECISIONS.md.

**Conventions**
- Ids are `str` (UUID4 hex from `IdGenerator`). Money is `Cents = int`. Times are timezone-aware UTC
  `datetime`; dates are `date`. Ordered collections are `tuple`, in participant order.
- Value objects and records are `@dataclass(frozen=True, slots=True)` and hold **no `dict`/`Mapping`
  fields** (they'd be unhashable and still mutable): per-person values are tuples of small records
  (`Share`, `Weight`). Helpers convert to/from `dict` at the edges of pure functions.
- Tagged unions are unions of frozen dataclasses with a distinct class per variant, so they round-trip
  through JSON/DB as `{"type": "<ClassName>", ...fields}`.
- `confidence` is the only float in the model and never takes part in money math.

**Where things live** (import-linter enforced): everything in §1 is in `smartsplit.domain`
(`domain/model.py`, `domain/messages.py`, `domain/prompts.py`, and §1.7's tool arguments in `domain/tools.py`, see DECISIONS M10); §2 in `smartsplit.engine`; §3 in
`smartsplit.ledger`; §4 in `smartsplit.ports` (incl. the port errors); the tool implementations and §5's
`Orchestrator` and `NotAllowedError` in `smartsplit.services`.
Error classes end in `Error` (ruff N818): `ReceiptUnreadableError`, `LlmUnavailableError`,
`NotAllowedError`; storage errors live in `smartsplit.ports.errors`: `StaleDraftError` and the
`ConstraintViolationError` family (`DuplicateKeyError`, `MissingReferenceError`,
`InvalidRecordError`), raised by both backends (see DECISIONS.md).

---

## 1. Domain

### 1.1 Enums (`StrEnum`, values are the lowercase names)

| Enum | Values |
|---|---|
| `RuleKind` | `exclude`, `soft_exclude`, `only` |
| `QuestionReason` | `soft_rule`, `no_eligible_members` |
| `RuleSource` | `stated`, `learned` |
| `ConversationKind` | `group`, `personal` |
| `DraftState` | `queued`, `awaiting_people`, `reviewing`, `saved`, `cancelled`, `expired` |
| `PromptKind` | `engine_question`, `pending_action` |
| `PromptStatus` | `open`, `answered`, `dropped` |
| `SettlementKind` | `payment`, `square_up` |
| `AnswerOutcome` | `excluded`, `sole_assignee`, `included` |
| `MatchHow` | `exact`, `alias`, `fuzzy`, `llm`, `none` |
| `PhotoOutcome` | `receipt`, `not_a_receipt`, `unreadable` |
| `NotificationKind` | `bill_added`, `bill_changed`, `payment_recorded`, `payment_reversed`, `square_up`, `reminder` |

### 1.2 Small records, scopes, contexts

```python
Cents = int

class Share:        person_id: str, cents: Cents
class Weight:       person_id: str, weight: int                 # weight >= 1

class ConversationKey:  channel: str, ref: str                  # globally unique pair

class Everywhere: ...
class GroupScope:   group_id: str
class NotesScope:   owner_id: str
RuleScope  = Everywhere | GroupScope | NotesScope
LocalScope = GroupScope | NotesScope        # where item aliases and answer observations live

class GroupContext:    group_id: str
class PersonalContext: ...
Context = GroupContext | PersonalContext

class EqualSplit:  people: tuple[str, ...]
class Weighted:    weights: tuple[Weight, ...]
Override = EqualSplit | Weighted            # exact amounts become Weighted via amounts_to_weights
```

### 1.3 People, places, items, rules

```python
class Person:         id, display_name: str, phone: str (E.164), phone_added_by: str | None,
                      notifications_enabled: bool, has_used_bot: bool, created_at
class ChatIdentity:   channel: str, external_ref: str, person_id     # unique (channel, external_ref);
                                                                     # a number and a hidden id are two refs
class Nickname:       owner_id, subject_id, name: str                # name stored normalized
class Group:          id, name: str, channel_ref: ConversationKey | None, created_at
class Membership:     group_id, person_id, position: int, joined_at, left_at: datetime | None
class Conversation:   key: ConversationKey, kind: ConversationKind, name: str | None,
                      group_id: str | None, person_id: str | None    # exactly one set

class Item:           key: str
class ItemAlias:      scope: LocalScope, raw_name: str, item_key: str
class Rule:           id, subject_id, item_key: str, kind: RuleKind, scope: RuleScope,
                      author_id, source: RuleSource, created_at
class AnswerObservation: scope: LocalScope, subject_id, item_key: str, outcome: AnswerOutcome,
                      bill_id, observed_at
class LlmUsage:       counter: str, day: date, calls: int    # counter: a person id, or "install";
                                                             # day in SMARTSPLIT_TIMEZONE
```

### 1.4 Photos, receipts, drafts, bills, payments

```python
class LineItem:   id, position: int, name: str, quantity: int, amount_cents: Cents,
                  taxed: bool | None, confidence: float, canonical: str | None,
                  discount_for: str | None, match_how: MatchHow, match_is_new: bool
                  # position = the line number people see; never renumbered within a draft

class Receipt:    id, image_ref: str, mime_type: str, merchant: str | None,
                  purchased_at: date | None, line_items: tuple[LineItem, ...],
                  tax_cents: Cents, other_adjustments_cents: Cents, total_cents: Cents,
                  warnings: tuple[str, ...]                          # immutable parse record

class PhotoRead:  conversation: ConversationKey, message_id: str, sender_id: str,
                  outcome: PhotoOutcome, receipt_id: str | None, used_by_draft_id: str | None,
                  created_at                                         # unique (conversation, message_id)

class BillDraft:  # mutable working copy, updated through the repository
                  id, conversation: ConversationKey, context: Context, added_by, payer_id,
                  receipt_id: str | None, description: str, purchased_at: date | None,
                  lines: tuple[LineItem, ...], tax_cents: Cents, other_adjustments_cents: Cents,
                  total_cents: Cents, participants: tuple[str, ...],
                  overrides: tuple[tuple[str, Override], ...], owes_all_id: str | None,
                  possible_duplicate_of: DuplicateRef | None, waiting_for: tuple[str, ...],
                  state: DraftState, version: int,
                  created_at, last_activity_at, reminded_at: datetime | None
class DuplicateRef: bill_id: str | None, draft_id: str | None        # exactly one set

class BillLine:   id, position: int, name: str, item_key: str, quantity: int,
                  amount_cents: Cents,          # before tax folding (as on the receipt / edited)
                  taxed: bool | None, discount_for: str | None, assignees: tuple[Weight, ...]
class Bill:       id, context: Context, origin: ConversationKey, receipt_id: str | None,
                  payer_id, added_by, description: str, purchased_at: date,
                  participants: tuple[str, ...], lines: tuple[BillLine, ...],
                  tax_cents: Cents, other_adjustments_cents: Cents,   # incl. accepted difference
                  total_cents: Cents, shares: tuple[Share, ...],
                  reverses_id: str | None, replaces_id: str | None, edit_reason: str | None,
                  created_at
    # A reversing bill copies purchased_at, negates every amount and share, and sets reverses_id.

class Settlement: id, payment_id, context: Context, from_id, to_id, amount_cents: Cents,
                  kind: SettlementKind, recorded_by, reverses_id: str | None, created_at
```

### 1.5 Prompts, transcript, notifications, delivery, idempotency

```python
class Prompt:     id, conversation: ConversationKey, draft_id: str | None, kind: PromptKind,
                  payload: EngineQuestionPayload | PendingActionPayload, status: PromptStatus,
                  asked_of: str | None,          # None = anyone in the context may answer
                  created_by, created_at, expires_at: datetime | None,
                  answers: tuple[PromptAnswer, ...]
class PromptAnswer: person_id, assignees: tuple[Weight, ...], at: datetime  # the line's new split

class EngineQuestionPayload:  line_id: str, member_id: str | None, reason: QuestionReason
class PendingActionPayload:   tool: str, arguments: ToolArgs,    # §1.7, with ids in place of handles
                              effect: Effect, based_on_version: int,
                              proposed_in_message_id: str        # "never in the same turn"
    # expires_at = proposed + 30 minutes; a new proposal of the same tool by the same person drops theirs

# What a pending action will do, exactly as restated. A "yes" applies it only if the affected data
# is still at based_on_version; otherwise the effect is recomputed and asked again.
class BillChangeEffect:  reverse_bill_id: str, new_bill: Bill | None
class PaymentEffect:     settlements: tuple[Settlement, ...], overpaid_cents: Cents
class RuleChangeEffect:  add: Rule | None, delete_rule_id: str | None
Effect = BillChangeEffect | PaymentEffect | RuleChangeEffect

class ChatRef:      kind: Literal["person", "bill", "draft", "line", "question", "action", "group",
                                  "payment"],
                    id: str, version: int | None                 # version: drafts, as shown
class ChatMessage:  conversation: ConversationKey, seq: int, sender_id: str | None,   # None = the bot
                    text: str, refs: tuple[ChatRef, ...], created_at
                    # shown blocks stored compactly: first lines + refs (SPEC §8.6)

class Notification: id, recipient_id, actor_id, kind: NotificationKind,
                    bill_ids: tuple[str, ...], payment_id: str | None, args: NotificationArgs,
                    created_at, sent_at: datetime | None
class NotificationArgs: reason: str | None, amount_cents: Cents | None
class TickBatch:    id, messages: tuple[OutboundMessage, ...], created_at, acked_at: datetime | None
class ProcessedMessage: key: ConversationKey, message_id: str,
                        replies: tuple[OutboundMessage, ...], processed_at
```

### 1.6 Messages (`domain/messages.py`)

```python
class ImageAttachment:   mime_type: str, data: bytes
class ContactAttachment: name: str, phone: str
class Mention:           ref: str, name: str, phone: str | None   # text carries "@<ref>"
class ChatEvent:         kind: Literal["participant_left", "bot_added"], subject_ref: str | None

class InboundMessage:    message_id: str, conversation: ConversationKey,
                         conversation_kind: ConversationKind, conversation_name: str | None,
                         sender_ref: str, sender_alt_ref: str | None,   # e.g. number + hidden id
                         sender_phone: str | None, sender_name: str,
                         addressed_to_bot: bool, reply_to_bot: bool, quoted_text: str | None,
                         mentions: tuple[Mention, ...],
                         text: str | None, image: ImageAttachment | None,
                         contact: ContactAttachment | None, event: ChatEvent | None
class OutboundMessage:   conversation: ConversationKey, recipient_id: str | None, text: str
                         # recipient_id set for personal-chat messages (the CLI prints "to Sam")
```

### 1.7 Tool arguments (`services/tools/`)

One frozen dataclass per tool (SPEC §8.3); the JSON schema the model sees is generated from it. Every
reference is a **handle** string issued for this turn (`P2`, `B3`, `D1`, `L4`, `Q1`, `A1`, `G1`, `T1` a payment) or
`"me"`; every amount is a `Money` string in major units (`"800"`, `"12.50"`), parsed by code into cents
(no floats; at most the currency's decimals; at most `SMARTSPLIT_MAX_AMOUNT_CENTS`). Code maps handles
to ids before running the tool, and stores ids, never handles.

| Tool | Arguments |
|---|---|
| `get_balances` | with_person: P \| None, group: G \| None, overall: bool |
| `get_bill` | bill: B \| D |
| `list_bills` | last_n: int \| None, period: `this_month` \| `last_month` \| None, text: str \| None, person: P \| None |
| `list_rules` | about: P |
| `find_person` | name: str |
| `start_receipt` | people: (P, …), everyone_except: (P, …), payer: P \| None, owes_all: P \| None, unknown_names: (str, …) |
| `add_manual_bill` | description, amount: Money, people, everyone_except, payer, owes_all, exact: ((P, Money), …), purchased_on: date \| None, unknown_names |
| `set_draft_people` | draft: D, people, everyone_except, group: G \| None |
| `edit_draft` | draft: D, change: one of `SetLineAmount(line: L, amount)`, `RemoveLine(line)`, `AddLine(name, amount)`, `SetTotal(amount)`, `AssignLine(line, people, weights: ((P, int), …), exact: ((P, Money), …))`, `UnassignLine(line: L \| None, people)`, `AddPeople(people)`, `RemovePeople(people)`, `NotThisItem(line, item_said: str \| None)`, `SetPayer(person)` |
| `answer_question` | question: Q, included: bool \| None, people: (P, …) (for "who's this for?") |
| `file_into_group` | draft: D, group: G |
| `confirm_draft` / `cancel_draft` | draft: D (+ keep_duplicate: bool, accept_difference: bool for confirm) |
| `add_person` | name: str, phone: str \| None, use_contact: bool, mention: P \| None |
| `join_group` | — |
| `member_left` | person: P (or "me") |
| `set_nickname` | person: P, nickname: str |
| `correct_number` | person: P, phone: str |
| `add_rule` / `delete_rule` | subject: P (or "me"), item: str, kind: RuleKind (add only) |
| `change_bill` | bill: B, change: `Delete` \| `NotMine` \| an `edit_draft` change, reason: str \| None |
| `record_payment` | from_person: P, to_person: P (one is "me"), amount: Money, group: G \| None |
| `square_up` | with_person: P |
| `not_received` / `undo_payment` | payment: T \| None (None = the latest one involving the speaker) |
| `confirm_pending` / `decline_pending` | action: A |
| `remind` | person: P |
| `set_notifications` | on: bool |

`unknown_names` lets a draft start while people are still to be found (SPEC §10.4).

---

## 2. Engine (`smartsplit.engine`, pure)

```python
# Frozen contract (exists): ItemInput, RuleInput, Question, Assignment, SplitResult
def split_receipt(items, members, rules=(), adjustments_cents=0, overrides=None) -> SplitResult

class TaxedLine:  item: ItemInput, taxed: bool | None
def fold_item_tax(lines: Sequence[TaxedLine], tax_cents: Cents) -> tuple[list[ItemInput], Cents]

def amounts_to_weights(line_cents: Cents, fixed: Sequence[tuple[str, Cents]],
                       others: Sequence[str]) -> tuple[Weight, ...]

class ResolvedRule: input: RuleInput, rule: Rule          # keeps scope/author for the summary
def resolve_rules(rules: Sequence[Rule], participants: Sequence[str], context: Context,
                  added_by: str) -> tuple[ResolvedRule, ...]

def discount_links(lines: Sequence[LineItem]) -> dict[str, str]   # linked discount → its line
def propagate_discount_overrides(lines: Sequence[LineItem],
                                 overrides: Sequence[tuple[str, Override]]) -> tuple[tuple[str, Override], ...]
    # a linked discount (negative, valid discount_for) follows its parent's override unless it has
    # its own; every other line, refunds included, is matched by name (Checkpoint A decision)

class Match: item_key: str | None, how: MatchHow
def match_item(raw_name: str, aliases: Mapping[str, str], known_keys: Collection[str],
               threshold: int) -> Match                   # how="none" → services ask the LLM

def observe(person_id: str, assignees: Sequence[str], *, weighted: bool) -> AnswerOutcome
    # removed → excluded; sole assignee of an unweighted line → sole_assignee; else included
def learned_kind(observations: Sequence[AnswerObservation], existing: Rule | None) -> RuleKind | None
    # last two observations both excluded → exclude, both sole_assignee → only;
    # returns None if existing is a stated exclude/only (a stated soft_exclude may be upgraded)

class DuplicateCandidate: id: str, is_draft: bool, context: Context, total_cents: Cents,
                          purchased_at: date | None, people: frozenset[str]
def find_likely_duplicate(context: Context, total_cents: Cents, purchased_at: date,
                          people: frozenset[str], candidates: Sequence[DuplicateCandidate],
                          *, window_days: int) -> DuplicateCandidate | None
    # same group context (or, for personal splits, same set of people); callers pass saved bills
    # that are neither reversed nor reversing, plus other active drafts
```

## 3. Ledger (`smartsplit.ledger`, pure)

Sign convention: a **positive** balance means the person **is owed** money.

```python
class ContextLedger:  context: Context, member_order: tuple[str, ...],
                      bills: tuple[Bill, ...], settlements: tuple[Settlement, ...]
    # member_order: groups = every membership ever, by position (leavers keep their place);
    # personal context = people sorted by id (only used for deterministic ordering)
class Transfer:       from_id, to_id, amount_cents: Cents       # from pays to
class Allocation:     context: Context, amount_cents: Cents
class OverallBalance: other_id, net_cents: Cents,               # >0: other owes me
                      breakdown: tuple[tuple[Context, Cents], ...]

def balances(ledger: ContextLedger) -> tuple[Share, ...]        # sums to 0
def simplify_debts(balances: Sequence[Share], order: Sequence[str]) -> tuple[Transfer, ...]
def pair_debts(ledger: ContextLedger) -> tuple[Transfer, ...]
    # groups: simplify_debts of the group; personal: raw pairs net of settlements
def overall_between(me: str, other: str, ledgers: Sequence[ContextLedger]) -> OverallBalance
def overall_for(me: str, ledgers: Sequence[ContextLedger]) -> tuple[OverallBalance, ...]
def allocate_payment(payer: str, payee: str, amount: Cents, ledgers: Sequence[ContextLedger],
                     named: Context | None) -> tuple[tuple[Allocation, ...], Cents]
    # second value: the part beyond what payer owed (overpayment). Unnamed: it goes to
    # PersonalContext. Named context: the whole amount stays there as a credit.
    # tie-break: the context whose oldest bill between the pair is oldest
def square_up(a: str, b: str, ledgers: Sequence[ContextLedger]) -> tuple[tuple[Context, Transfer], ...]
```

Property tests required in M4: balances always sum to 0; settling a shown pair amount in a group makes
that pair 0 after re-simplifying (if greedy can't guarantee it, `square_up` iterates until every
context's A–B pair is 0 and the test asserts that).

## 4. Ports (`smartsplit.ports`, Protocols)

```python
class Clock(Protocol):
    def now(self) -> datetime: ...  # tz-aware UTC


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class ImageStore(Protocol):
    def save(self, data: bytes, mime_type: str) -> str: ...  # returns image_ref
    def load(self, image_ref: str) -> bytes: ...
    def prune(self, older_than: datetime) -> int: ...


class ReceiptParser(Protocol):
    def parse(
        self, image: bytes, mime_type: str, currency: str, timeout_seconds: float
    ) -> ParsedReceipt | NotAReceipt: ...


class Canonicalizer(Protocol):  # all that item matching needs
    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str: ...


class AgentModel(Protocol):  # §4.2
    def step(self, request: AgentRequest) -> ModelStep: ...


class Repository(Protocol):
    def unit_of_work(
        self,
        lock: ConversationKey | None = None,
        *,
        lock_wait_seconds: float | None = None,
        try_lock: bool = False,
    ) -> AbstractContextManager[UnitOfWork]: ...

    # one transaction; commits on success, rolls back on exception; optional per-conversation lock.
    # A lock not taken within lock_wait_seconds raises ChatBusyError; with try_lock it raises at once.


class ReceiptUnreadableError(Exception): ...  # bad image / invalid output after the retry


class LlmUnavailableError(Exception): ...  # timeout / API error after the retry


class ChatBusyError(Exception): ...  # the conversation lock wasn't free in time
```

`UnitOfWork` exposes one store per aggregate (each a Protocol with get/add/update and the queries the
services need; method lists in `ports/repository.py`): `people`, `identities`, `nicknames`, `groups`,
`memberships`, `conversations`, `items`, `aliases`, `rules`, `observations`, `photos`, `receipts`,
`drafts`, `prompts`, `bills`, `settlements`, `chat`, `notifications`, `tick_batches`, `processed`,
`llm_usage`. Notable queries:
- `drafts.update(draft, expected_version)` raises `StaleDraftError` if the draft changed;
  `drafts.due_for_reminder_or_expiry(idle_since)`.
- `photos.latest_unused(conversation, sender_id, since)` (SPEC §10.4).
- `chat.append(message)`, `chat.recent(key, limit)`, `chat.prune(key, keep)`,
  `chat.delete_older_than(before) -> int`; `seq` from one sequence, so appending to another chat
  needs no lock on it.
- `notifications.claim_due(now, limit, per_person_daily_cap, day_start)` (claims serialized by an
  advisory lock, rows taken with SKIP LOCKED); `tick_batches.unacked_before(when)`, `ack(batch_id)`.
- `Repository.count_usage(counter, day)` counts one model call in its own committed transaction,
  never inside a turn's; `llm_usage.get` reads the counts.
- `UnitOfWork.savepoint()`: a block whose writes are undone if it raises (one tool call).

### 4.1 Parser output

```python
class ParsedLine:     name: str, quantity: int, amount_cents: Cents, taxed: bool | None,
                      confidence: float, discount_for_index: int | None
class ParsedReceipt:  merchant: str | None, purchased_at: date | None,
                      lines: tuple[ParsedLine, ...], tax_cents: Cents,
                      other_adjustments_cents: Cents, total_cents: Cents,
                      currency: str | None, warnings: tuple[str, ...]
class NotAReceipt:    ...
```

### 4.2 Agent model (SPEC §8)

```python
class ToolSpec:   name: str, description: str, input_schema: Mapping[str, object]
class ToolCall:   id: str, name: str, arguments: Mapping[str, object]
class ToolResult: call_id: str, ok: bool, data: Mapping[str, object], error: str | None,
                  shown: tuple[str, ...]          # code-rendered text appended to the reply (SPEC §8.5)
class ModelUsage: input_tokens, cache_read_tokens, cache_write_tokens, output_tokens: int
class ModelStep:  tool_calls: tuple[ToolCall, ...], text: str | None, usage: ModelUsage,
                  replay: tuple[Mapping[str, object], ...]   # provider blocks, sent back unchanged
                  # no tool calls → the turn ends; `text` (may be empty) is the model's part of the reply
class AgentRequest:
    system: str
    tools: tuple[ToolSpec, ...]                   # always the fixed list (the cached prefix)
    turn_input: str                               # <state>…</state><recent_chat>…</recent_chat><message>…</message>
    history: tuple[tuple[ModelStep, tuple[ToolResult, ...]], ...]   # this turn's earlier steps only
    timeout_seconds: float                        # min(LLM timeout, time left for the message)
    final: bool                                   # the last allowed step: no tool may be called

class AgentModel(Protocol):
    def step(self, request: AgentRequest) -> ModelStep: ...   # raises LlmUnavailableError
```

Handles are per-turn strings; the service keeps the handle → id map for the turn (including handles
returned by tool results) and rejects any handle it didn't issue.

## 5. Orchestrator (`smartsplit.services`)

```python
class HandleOutcome:  replies: tuple[OutboundMessage, ...], busy: bool   # busy → HTTP 503
class Orchestrator:
    def handle(self, message: InboundMessage) -> HandleOutcome: ...      # one message, SPEC §8.1
    def tick(self) -> TickBatch: ...                                     # uses Clock.now()
    def ack(self, batch_id: str) -> None: ...
```

- `handle` returns messages for **any** conversation: replies to the current chat, posts to a group
  chat (a bill filed from a personal chat), DMs (answers sent privately from a group). Personal-chat
  notifications go through the outbox and leave through `tick`.
- `handle` reads a photo before taking the lock and stores the `PhotoRead` in its own transaction;
  the agent turn is one locked transaction; usage counts are written in their own transactions.
- **HTTP:** the same field names in snake_case; `conversation` is `{"channel": ..., "ref": ...}`;
  images inline as `"image": {"mime_type": "image/jpeg", "data_base64": "..."}`, size-limited.

```json
POST /v1/messages
{"message_id": "wamid.123", "conversation": {"channel": "whatsapp", "ref": "1203630@g.us"},
 "conversation_kind": "group", "conversation_name": "Flat 4B",
 "sender_ref": "+919876543210", "sender_alt_ref": "123456@lid", "sender_phone": "+919876543210",
 "sender_name": "Sam", "addressed_to_bot": true, "reply_to_bot": false, "quoted_text": null,
 "mentions": [{"ref": "+919800000001", "name": "Raj", "phone": "+919800000001"}],
 "text": "split this, @+919800000001 paid", "image": {"mime_type": "image/jpeg", "data_base64": "..."}}
→ 200 [{"conversation": {"channel": "whatsapp", "ref": "1203630@g.us"}, "recipient_id": null,
        "text": "Toit, ₹1,200 …"}]

POST /v1/tick → 200 {"batch_id": "…", "messages": [...]}
POST /v1/tick/{batch_id}/ack → 204
```

## 6. Errors

| Error | Lives in | Handled as |
|---|---|---|
| `ValueError` | pure layers, invalid input | a bug if it reaches the user; services validate first |
| `ReceiptUnreadableError` | ports | the photo is stored as `unreadable`; the model tells the person |
| `LlmUnavailableError` | ports | "Couldn't do that, try again in a minute"; the turn rolls back |
| `ChatBusyError` | ports | HTTP 503 with `Retry-After`; nothing recorded |
| `NotAllowedError` | services | a tool error with a short reason the model passes on ("Only Sam can delete that rule") |
| `StaleDraftError` | ports | the turn rolls back like any failure (a concurrent change slipped past the lock) |
