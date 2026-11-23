# SmartSplit — Data shapes and contracts (DRAFT, under review with the user)

The concrete types and interfaces every milestone builds against. SPEC.md says *what* happens;
this file says *what the data looks like*. Python-style signatures; all dataclasses are
`@dataclass(frozen=True)` unless noted. Field names here are final once agreed; changing them later
is a decision to log in DECISIONS.md.

Conventions: ids are `str` (UUID4 hex); money is `Cents = int`; times are timezone-aware UTC
`datetime`; dates are `date`. Ordered collections are `tuple`. Lists of people keep participant order.

---

## 1. Domain (`smartsplit.domain`)

### 1.1 Enums (`StrEnum`, values are the lowercase names)

| Enum | Values |
|---|---|
| `RuleKind` (exists) | `exclude`, `soft_exclude`, `only` |
| `QuestionReason` (exists) | `soft_rule`, `no_eligible_members` |
| `RuleSource` | `stated`, `learned` |
| `ConversationKind` | `group`, `personal` |
| `DraftState` | `queued`, `awaiting_people`, `parsing`, `reviewing`, `saved`, `cancelled`, `expired` |
| `PromptKind` | `engine_question`, `who_with`, `which_person`, `need_contact`, `confirm_total`, `confirm_line`, `confirm_action`, `join_group`, `duplicate_warning` |
| `PromptStatus` | `open`, `answered`, `dropped` |
| `SettlementKind` | `payment`, `square_up` |
| `AnswerOutcome` | `excluded`, `sole_assignee`, `included` |
| `NotificationKind` | `bill_added`, `bill_changed`, `payment_recorded`, `payment_reversed`, `square_up`, `reminder`, `rule_about_you` |

### 1.2 Scopes and contexts

```python
@dataclass(frozen=True)
class Everywhere: ...

@dataclass(frozen=True)
class GroupScope:
    group_id: str

@dataclass(frozen=True)
class NotesScope:
    owner_id: str

RuleScope = Everywhere | GroupScope | NotesScope
MatchScope = GroupScope | NotesScope           # where item aliases are remembered

@dataclass(frozen=True)
class GroupContext:
    group_id: str

@dataclass(frozen=True)
class PersonalContext: ...

Context = GroupContext | PersonalContext
```

### 1.3 Entities

```python
class Person:            id, display_name: str, phone: str (E.164), notifications_enabled: bool,
                         has_used_bot: bool, created_at: datetime
class ChatIdentity:      channel: str, external_ref: str, person_id: str
class Nickname:          owner_id, subject_id, name: str          # name stored normalized
class Group:             id, name: str, channel_ref: str | None, created_at
class Membership:        group_id, person_id, position: int, joined_at, left_at: datetime | None
class Conversation:      channel: str, ref: str, kind: ConversationKind,
                         group_id: str | None, person_id: str | None   # exactly one set

class ItemAlias:         match_scope: MatchScope, raw_name: str, item_key: str
class Rule:              id, subject_id, item_key: str, kind: RuleKind, scope: RuleScope,
                         author_id, source: RuleSource, created_at
class AnswerObservation: scope: RuleScope, subject_id, item_key: str, outcome: AnswerOutcome,
                         bill_id, observed_at

class LineItem:          id, name: str, quantity: int, amount_cents: Cents, taxed: bool | None,
                         confidence: float, canonical: str | None, discount_for: str | None
class Receipt:           id, context: Context, merchant: str | None, purchased_at: date | None,
                         line_items: tuple[LineItem, ...], tax_cents: Cents,
                         other_adjustments_cents: Cents, total_cents: Cents,
                         image_ref: str | None, warnings: tuple[str, ...]

class BillLine:          name: str, item_key: str, amount_cents: Cents,
                         assignees: Mapping[str, int]              # person_id -> weight
class Bill:              id, context: Context, receipt_id: str | None, payer_id, added_by,
                         description: str, purchased_at: date, participants: tuple[str, ...],
                         lines: tuple[BillLine, ...], total_cents: Cents,
                         shares: Mapping[str, Cents], reverses_id: str | None,
                         replaces_id: str | None, edit_reason: str | None, created_at
class Settlement:        id, payment_id, context: Context, from_id, to_id, amount_cents: Cents,
                         kind: SettlementKind, recorded_by, reverses_id: str | None, created_at

# Mutable state (plain dataclasses, updated through the repository)
class BillDraft:         id, conversation_ref, context: Context, added_by, payer_id,
                         receipt_id: str | None, manual_lines: tuple[LineItem, ...],
                         participants: tuple[str, ...], overrides: Mapping[str, Override],
                         state: DraftState, created_at, last_activity_at, reminded_at: datetime | None
class Prompt:            id, conversation_ref, draft_id: str | None, kind: PromptKind,
                         payload: Mapping[str, object], status: PromptStatus,
                         answers: tuple[PromptAnswer, ...]
class PromptAnswer:      person_id, answer: str, at: datetime
class Notification:      id, person_id, kind: NotificationKind, bill_ids: tuple[str, ...],
                         payload: Mapping[str, object], created_at, sent_at: datetime | None
class ProcessedMessage:  channel, message_id, replies: tuple[OutboundMessage, ...], processed_at
```

`Override = Sequence[str] | Mapping[str, int]` (equal split, or person → weight; exact amounts are
converted to weights with `amounts_to_weights` before they are stored).

### 1.4 Helpers (pure)

```python
def normalize_item_name(name: str) -> str                         # exists
def normalize_phone(raw: str, default_region: str) -> str         # E.164; ValueError if invalid
def mask_phone(e164: str) -> str                                  # "+91•••••43210"
```

---

## 2. Engine (`smartsplit.engine`, pure)

```python
# Frozen contract (exists): ItemInput, RuleInput, Question, Assignment, SplitResult
def split_receipt(items, members, rules=(), adjustments_cents=0, overrides=None) -> SplitResult

class TaxedLine:  item: ItemInput, taxed: bool | None
def fold_item_tax(lines: Sequence[TaxedLine], tax_cents: Cents) -> tuple[list[ItemInput], Cents]

def amounts_to_weights(line_cents: Cents, fixed: Mapping[str, Cents],
                       others: Sequence[str]) -> dict[str, int]

def resolve_rules(rules: Sequence[Rule], participants: Sequence[str], context: Context,
                  added_by: str) -> list[RuleInput]

class Match:      item_key: str | None, how: Literal["exact", "alias", "fuzzy", "none"]
def match_item(raw_name: str, aliases: Mapping[str, str], known_keys: Collection[str],
               threshold: int) -> Match                           # "none" → services ask the LLM

def learned_kind(observations: Sequence[AnswerObservation]) -> RuleKind | None   # last two, §6.5

def find_likely_duplicate(candidate_total: Cents, purchased_at: date, people: frozenset[str],
                          recent: Sequence[Bill], window_days: int) -> Bill | None
```

## 3. Ledger (`smartsplit.ledger`, pure)

Sign convention: a **positive** balance means the person **is owed** money.

```python
class ContextLedger:  context: Context, member_order: tuple[str, ...],
                      bills: tuple[Bill, ...], settlements: tuple[Settlement, ...]
class Transfer:       from_id, to_id, amount_cents: Cents          # from pays to
class Allocation:     context: Context, amount_cents: Cents
class OverallBalance: other_id, net_cents: Cents,                  # >0: other owes me
                      breakdown: tuple[tuple[Context, Cents], ...]

def balances(ledger: ContextLedger) -> dict[str, Cents]            # sums to 0
def simplify_debts(balances: Mapping[str, Cents], order: Sequence[str]) -> list[Transfer]
def pair_debts(ledger: ContextLedger) -> dict[tuple[str, str], Cents]
    # (debtor, creditor) -> cents; groups: from simplify_debts, personal: raw pairs
def overall_between(me: str, other: str, ledgers: Sequence[ContextLedger]) -> OverallBalance
def allocate_payment(payer: str, payee: str, amount: Cents, ledgers: Sequence[ContextLedger],
                     named: Context | None) -> tuple[list[Allocation], Cents]
    # second value: the part beyond what payer owed (overpayment, needs confirmation)
def square_up(a: str, b: str, ledgers: Sequence[ContextLedger]) -> list[tuple[Context, Transfer]]
```

`square_up` returns, per context, the transfer that zeroes it (`Transfer` with that context), plus
the net placed in `PersonalContext`; the service turns them into `square_up` settlements.

---

## 4. Ports (`smartsplit.ports`, Protocols)

```python
class Clock(Protocol):
    def now(self) -> datetime: ...                                 # tz-aware UTC

class IdGenerator(Protocol):
    def new_id(self) -> str: ...

class ReceiptParser(Protocol):
    def parse(self, image: bytes, mime_type: str, currency: str) -> ParsedReceipt: ...
    # raises ReceiptUnreadable (bad image / invalid output after retry)
    #        LlmUnavailable    (timeout / API error after retry)

class CommandInterpreter(Protocol):
    def interpret(self, text: str, context: InterpretContext) -> Command: ...
    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str: ...
    # raises LlmUnavailable

class Repository(Protocol):
    def unit_of_work(self, lock_conversation: str | None = None) -> ContextManager[UnitOfWork]: ...
    # one transaction; commits on success, rolls back on exception; optional per-conversation lock
```

`UnitOfWork` exposes one small store per aggregate (each a Protocol with the obvious get/add/update
and the queries the services need, finalized in M2): `people`, `identities`, `nicknames`, `groups`,
`memberships`, `conversations`, `aliases`, `rules`, `observations`, `receipts`, `bills`,
`settlements`, `drafts`, `prompts`, `notifications`, `processed`. Two special queries:
`notifications.claim_due(now, limit)` (SKIP LOCKED) and `drafts.due_for_reminder_or_expiry(now)`.

### 4.1 Parser output

```python
class ParsedLine:     name: str, quantity: int, amount_cents: Cents, taxed: bool | None,
                      confidence: float, discount_for_index: int | None
class ParsedReceipt:  merchant: str | None, purchased_at: date | None,
                      lines: tuple[ParsedLine, ...], tax_cents: Cents,
                      other_adjustments_cents: Cents, total_cents: Cents,
                      currency: str | None, warnings: tuple[str, ...]
```

### 4.2 Interpreter input and output

```python
class NameablePerson:  person_id, names: tuple[str, ...]          # nickname(s) + display name
class InterpretContext: conversation_kind: ConversationKind, speaker_id,
                        nameable: tuple[NameablePerson, ...], group_names: tuple[str, ...],
                        open_prompts: tuple[Prompt, ...], draft_summary: str | None
```

`Command` is a tagged union. People are referred to **by name as said** (`PersonRef = str`); services
resolve them (§6.1 of the SPEC). Amounts are `Cents`.

| Command | Fields |
|---|---|
| `StartSplit` | people: tuple[PersonRef, ...], everyone: bool, except_: tuple[PersonRef, ...], payer: PersonRef \| None, owes_all: PersonRef \| None |
| `AddManualBill` | description, amount, people, everyone, except_, exact: Mapping[PersonRef, Cents], purchased_on: date \| None |
| `AnswerPrompt` | prompt_id: str \| None, answer: str |
| `EditDraft` | op: `set_amount` \| `remove_line` \| `add_line` \| `set_total` \| `assign` \| `not_this_item`, line: str \| None (number or name), amount: Cents \| None, name: str \| None, people: tuple[PersonRef, ...], weights: Mapping[PersonRef, int], exact: Mapping[PersonRef, Cents] |
| `ConfirmDraft` / `CancelDraft` | — |
| `FileIntoGroup` | group_name |
| `EditBill` | bill: str \| None ("last", a number, or a name), change: EditDraft, reason: str \| None |
| `DeleteBill` | bill: str \| None, reason: str \| None |
| `NotMine` | bill: str \| None |
| `ShowBillDetails` | bill: str \| None |
| `AddPerson` | name, phone: str \| None (contact cards arrive as attachments) |
| `JoinGroup` / `AddMember` / `MemberLeft` | person: PersonRef \| None (None = speaker) |
| `SetNickname` | person: PersonRef, nickname |
| `CorrectNumber` | person: PersonRef, phone |
| `AddRule` | subject: PersonRef \| None (None = speaker), item: str, kind: RuleKind |
| `DeleteRule` | subject: PersonRef \| None, item: str |
| `ListRules` | subject: PersonRef \| None |
| `ShowBalances` | with_: PersonRef \| None, group_name: str \| None |
| `RecordPayment` | payer: PersonRef \| None, payee: PersonRef \| None (one of them is the speaker), amount, context_name: str \| None |
| `NotReceived` / `UndoPayment` | — |
| `SquareUp` | with_: PersonRef |
| `Remind` | person: PersonRef |
| `ShowHistory` | period: `this_month` \| `last_month` \| None, last_n: int \| None |
| `Notifications` | on: bool |
| `Help` / `Unknown` | Unknown carries the original text |

---

## 5. Messages (`smartsplit.services`, and the HTTP API)

```python
class ImageAttachment:   mime_type: str, data: bytes
class ContactAttachment: name: str, phone: str
class ChatEvent:         kind: Literal["participant_left"], subject_ref: str

class InboundMessage:    message_id: str, channel: str, conversation_ref: str,
                         conversation_kind: ConversationKind, sender_ref: str,
                         sender_phone: str | None, sender_name: str,
                         addressed_to_bot: bool, reply_to_bot: bool,
                         text: str | None, image: ImageAttachment | None,
                         contact: ContactAttachment | None, event: ChatEvent | None
class OutboundMessage:   conversation_ref: str, text: str
```

Service entry points (the only things entrypoints call):

```python
class Orchestrator:
    def handle(self, message: InboundMessage) -> list[OutboundMessage]: ...
    def tick(self) -> list[OutboundMessage]: ...
```

HTTP JSON uses the same field names in snake_case. Images are sent inline as
`"image": {"mime_type": "image/jpeg", "data_base64": "..."}`, size-limited by `SMARTSPLIT_MAX_IMAGE_BYTES`.
Example:

```json
POST /v1/messages
{"message_id": "wamid.123", "channel": "whatsapp", "conversation_ref": "1203630@g.us",
 "conversation_kind": "group", "sender_ref": "+919876543210", "sender_phone": "+919876543210",
 "sender_name": "Sam", "addressed_to_bot": true, "reply_to_bot": false,
 "text": "split this, Sam paid", "image": {"mime_type": "image/jpeg", "data_base64": "..."}}
→ 200 [{"conversation_ref": "1203630@g.us", "text": "Toit, ₹1,200 …"}]
```

## 6. Errors

| Error | Raised by | Handled as |
|---|---|---|
| `ValueError` | pure layers on invalid input | a bug if it reaches the user; services validate first |
| `ReceiptUnreadable` | ReceiptParser | "Couldn't read that receipt, try another photo" |
| `LlmUnavailable` | ReceiptParser, CommandInterpreter | "Couldn't do that, try again in a minute"; nothing changes |
| `NotAllowed` | services (permission checks) | short plain refusal ("Only Sam can delete that rule") |
| `NeedsClarification` | services (name resolution, ambiguous bill) | becomes a `Prompt` |
