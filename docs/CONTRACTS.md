# SmartSplit — Data shapes and contracts (v2, agreed with the user 2026-11-23)

The concrete types and interfaces every milestone builds against. SPEC.md says *what* happens;
this file says *what the data looks like*. Python-style signatures. Field names are final once
agreed; changing them later is a decision to log in DECISIONS.md.

**Conventions**
- Ids are `str` (UUID4 hex from `IdGenerator`). Money is `Cents = int`. Times are timezone-aware UTC
  `datetime`; dates are `date`. Ordered collections are `tuple`, in participant order.
- Value objects and records are `@dataclass(frozen=True, slots=True)` and hold **no `dict`/`Mapping`
  fields** (they'd be unhashable and still mutable): per-person values are tuples of small records
  (`Share`, `Weight`, `ExactAmount`). Helpers convert to/from `dict` at the edges of pure functions.
- Tagged unions are unions of frozen dataclasses with a distinct class per variant, so they round-trip
  through JSON/DB as `{"type": "<ClassName>", ...fields}`.
- `confidence` is the only float in the model and never takes part in money math.

**Where things live** (import-linter enforced): everything in §1 is in `smartsplit.domain`
(`domain/model.py`, `domain/messages.py`, `domain/commands.py`, `domain/prompts.py`); §2 in
`smartsplit.engine`; §3 in `smartsplit.ledger`; §4 in `smartsplit.ports` (incl. the port errors);
§5's `Orchestrator` and the `NotAllowedError`/`NeedsClarification` errors in `smartsplit.services`.
Error classes end in `Error` (ruff N818): `ReceiptUnreadableError`, `LlmUnavailableError`,
`NotAllowedError`; storage errors live in `smartsplit.ports.errors`: `StaleDraftError` and the
`ConstraintViolationError` family (`DuplicateKeyError`, `MissingReferenceError`,
`InvalidRecordError`), raised by both backends (see DECISIONS.md).

---

## 1. Domain

### 1.1 Enums (`StrEnum`, values are the lowercase names)

| Enum | Values |
|---|---|
| `RuleKind` (exists) | `exclude`, `soft_exclude`, `only` |
| `QuestionReason` (exists) | `soft_rule`, `no_eligible_members` |
| `RuleSource` | `stated`, `learned` |
| `ConversationKind` | `group`, `personal` |
| `DraftState` | `queued`, `awaiting_people`, `parsing`, `reviewing`, `saved`, `cancelled`, `expired` |
| `PromptKind` | `engine_question`, `who_with`, `which_person`, `need_contact`, `confirm_total`, `confirm_line`, `confirm_action`, `join_group`, `duplicate_warning` |
| `PromptStatus` | `pending` (not yet asked, e.g. later question batch), `open`, `answered`, `dropped` |
| `SettlementKind` | `payment`, `square_up` |
| `AnswerOutcome` | `excluded`, `sole_assignee`, `included` |
| `MatchHow` | `exact`, `alias`, `fuzzy`, `llm`, `none` |
| `NotificationKind` | `bill_added`, `bill_changed`, `payment_recorded`, `payment_reversed`, `square_up`, `reminder`, `requested_reply` |

### 1.2 Small records, scopes, contexts, references

```python
Cents = int

class Share:        person_id: str, cents: Cents
class Weight:       person_id: str, weight: int                 # weight >= 1
class ExactAmount:  person: PersonRef, cents: Cents             # as said, before resolution

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

PersonRef = str                             # a name or number as said; services resolve it
class LastBill: ...
class NumberedBill: n: int                  # from the speaker's last numbered list
class NamedBill:    text: str               # "the Toit bill"
BillRef = LastBill | NumberedBill | NamedBill
LineRef = int | str                         # line number in the shown list, or a name
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
                      group_id: str | None, person_id: str | None,   # exactly one set
                      last_listed_bill_ids: tuple[str, ...]          # resolves NumberedBill

class Item:           key: str
class ItemAlias:      scope: LocalScope, raw_name: str, item_key: str
class Rule:           id, subject_id, item_key: str, kind: RuleKind, scope: RuleScope,
                      author_id, source: RuleSource, created_at
class AnswerObservation: scope: LocalScope, subject_id, item_key: str, outcome: AnswerOutcome,
                      bill_id, observed_at
class LlmUsage:       person_id, day: date, calls: int               # day in SMARTSPLIT_TIMEZONE
```

### 1.4 Receipts, drafts, bills, payments

```python
class LineItem:   id, position: int, name: str, quantity: int, amount_cents: Cents,
                  taxed: bool | None, confidence: float, canonical: str | None,
                  discount_for: str | None, match_how: MatchHow, match_is_new: bool

class Receipt:    id, image_ref: str, mime_type: str, merchant: str | None,
                  purchased_at: date | None, line_items: tuple[LineItem, ...],
                  tax_cents: Cents, other_adjustments_cents: Cents, total_cents: Cents,
                  warnings: tuple[str, ...]                          # immutable parse record

class BillDraft:  # mutable working copy, updated through the repository
                  id, conversation: ConversationKey, context: Context, added_by, payer_id,
                  receipt_id: str | None, image_ref: str | None, image_mime_type: str | None,
                  description: str, purchased_at: date | None,
                  lines: tuple[LineItem, ...], tax_cents: Cents, other_adjustments_cents: Cents,
                  total_cents: Cents, accepted_difference_cents: Cents,
                  participants: tuple[str, ...], overrides: tuple[tuple[str, Override], ...],
                  owes_all_id: str | None, state: DraftState,
                  created_at, last_activity_at, reminded_at: datetime | None

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

### 1.5 Prompts, notifications, idempotency

```python
class Prompt:     id, conversation: ConversationKey, draft_id: str | None, kind: PromptKind,
                  payload: PromptPayload, status: PromptStatus,
                  asked_of: str | None,          # None = anyone in the context may answer
                  created_by, created_at, answers: tuple[PromptAnswer, ...]
class PromptAnswer: person_id, answer: AnswerPrompt, at: datetime

class EngineQuestionPayload:  line_id: str, member_id: str | None, reason: QuestionReason
class WhoWithPayload:         options: tuple[ListOption, ...]
class ListOption:             n: int, person_ids: tuple[str, ...], group_id: str | None, label: str
class WhichPersonPayload:     said: PersonRef, candidate_ids: tuple[str, ...], pending: Command
class NeedContactPayload:     said: PersonRef, pending: Command
class ConfirmTotalPayload:    difference_cents: Cents
class ConfirmLinePayload:     line_id: str
class ConfirmActionPayload:   command: Command, effect: Effect, based_on_version: int
class JoinGroupPayload:       person_id: str
class DuplicateWarningPayload: other_bill_id: str | None, other_draft_id: str | None
PromptPayload = (EngineQuestionPayload | WhoWithPayload | WhichPersonPayload | NeedContactPayload
                 | ConfirmTotalPayload | ConfirmLinePayload | ConfirmActionPayload
                 | JoinGroupPayload | DuplicateWarningPayload)

# What a confirm_action will do, exactly as restated. "yes" applies it only if the affected data
# is still at based_on_version; otherwise the effect is recomputed and asked again.
class BillChangeEffect:  reverse_bill_id: str | None, new_bill: Bill | None
class PaymentEffect:     settlements: tuple[Settlement, ...], overpaid_cents: Cents
class RuleChangeEffect:  add: Rule | None, delete_rule_id: str | None
Effect = BillChangeEffect | PaymentEffect | RuleChangeEffect

class Notification: id, recipient_id, actor_id, kind: NotificationKind,
                    bill_ids: tuple[str, ...], payment_id: str | None, text_args: NotificationArgs,
                    created_at, sent_at: datetime | None
class NotificationArgs: reason: str | None, amount_cents: Cents | None, body: str | None
    # body is used only by requested_reply (already-rendered text); others render at send time
class ProcessedMessage: key: ConversationKey, message_id: str,
                        replies: tuple[OutboundMessage, ...], processed_at
```

### 1.6 Messages (`domain/messages.py`)

```python
class ImageAttachment:   mime_type: str, data: bytes
class ContactAttachment: name: str, phone: str
class ChatEvent:         kind: Literal["participant_left"], subject_ref: str

class InboundMessage:    message_id: str, conversation: ConversationKey,
                         conversation_kind: ConversationKind, conversation_name: str | None,
                         sender_ref: str, sender_alt_ref: str | None,   # e.g. number + hidden id
                         sender_phone: str | None, sender_name: str,
                         addressed_to_bot: bool, reply_to_bot: bool,
                         text: str | None, image: ImageAttachment | None,
                         contact: ContactAttachment | None, event: ChatEvent | None
class OutboundMessage:   conversation: ConversationKey, recipient_id: str | None, text: str
                         # recipient_id set for personal-chat messages (the CLI prints "to Sam")
```

### 1.7 Commands (`domain/commands.py`)

The interpreter returns exactly one `Command`. People are `PersonRef`s (names as said); the model
never supplies ids. Whether "yes" means `ConfirmDraft` or an answer is decided by the services from
the open prompts, not by the model (the interpreter returns `AnswerPrompt(yes=True)`).

| Command | Fields |
|---|---|
| `StartSplit` | people, everyone: bool, excluding, payer: PersonRef \| None, owes_all: PersonRef \| None |
| `AddManualBill` | description, amount, people, everyone, excluding, payer, owes_all, exact: tuple[ExactAmount, ...], purchased_on: date \| None |
| `AnswerPrompt` | prompt_id: str \| None, yes: bool \| None, choice: int \| None, people, excluding, text: str \| None |
| `Edit` | target: BillRef \| None (None = the active draft), op: EditOp, reason: str \| None |
| `ConfirmDraft` / `CancelDraft` / `Acknowledge` | — (`Acknowledge` = "ok" to a notification; no reply) |
| `FileIntoGroup` | group_name |
| `DeleteBill` | target: BillRef, reason: str \| None |
| `NotMine` | target: BillRef \| None |
| `ShowBillDetails` | target: BillRef \| None |
| `AddPerson` | name, phone: str \| None (contact cards arrive as attachments). In a group chat this adds a member. |
| `JoinGroup` | — (the speaker) |
| `MemberLeft` | person: PersonRef \| None (None = the speaker) |
| `SetNickname` | person, nickname |
| `CorrectNumber` | person, phone |
| `AddRule` / `DeleteRule` | subject: PersonRef \| None (None = speaker), item: str, kind: RuleKind (AddRule only) |
| `ListRules` | subject: PersonRef \| None |
| `ShowBalances` | with_person: PersonRef \| None, group_name: str \| None |
| `RecordPayment` | payer: PersonRef \| None, payee: PersonRef \| None (one of them is the speaker), amount, context_name: str \| None |
| `NotReceived` / `UndoPayment` | — |
| `SquareUp` | with_person |
| `Remind` | person |
| `ShowHistory` | period: `this_month` \| `last_month` \| None, last_n: int \| None |
| `Notifications` | on: bool |
| `Help` / `Unknown` | `Unknown` carries the original text |

`people`/`excluding` are `tuple[PersonRef, ...]`; amounts are `Cents`.

`EditOp` (one dataclass each): `SetLineAmount(line, amount)`, `RemoveLine(line)`, `AddLine(name, amount)`,
`SetTotal(amount)`, `AssignLine(line, people, weights: tuple[tuple[PersonRef, int], ...], exact)`,
`UnassignLine(line: LineRef | None, people)` (None = every line), `AddParticipants(people)`,
`RemoveParticipants(people)`, `AcceptDifference()`, `NotThisItem(line, item_said)`, `SetPayer(person)`.

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
                          window_days: int) -> DuplicateCandidate | None
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
    def parse(self, image: bytes, mime_type: str, currency: str) -> ParsedReceipt: ...


class Canonicalizer(Protocol):  # all that item matching needs (M3)
    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str: ...


class CommandInterpreter(Canonicalizer, Protocol):
    def interpret(self, text: str, context: InterpretContext) -> Command: ...


class Repository(Protocol):
    def unit_of_work(
        self, lock: ConversationKey | None = None
    ) -> AbstractContextManager[UnitOfWork]: ...

    # one transaction; commits on success, rolls back on exception; optional per-conversation lock


class ReceiptUnreadableError(Exception): ...  # bad image / invalid output after the retry


class LlmUnavailableError(Exception): ...  # timeout / API error after the retry
```

`UnitOfWork` exposes one store per aggregate (each a Protocol with get/add/update and the queries the
services need; method lists finalized in M2): `people`, `identities`, `nicknames`, `groups`,
`memberships`, `conversations`, `items`, `aliases`, `rules`, `observations`, `receipts`, `drafts`,
`prompts`, `bills`, `settlements`, `notifications`, `processed`, `llm_usage` (exposed as read-only
properties; method lists in `ports/repository.py`). `drafts.update(draft, expected_state)` raises
`StaleDraftError` if the state changed. Special queries:
`notifications.claim_due(now, limit, per_person_daily_cap, day_start)` (claims serialized by an
advisory lock, rows taken with SKIP LOCKED; the cap counts
sent notifications except `requested_reply` since `day_start` in the install timezone) and
`drafts.due_for_reminder_or_expiry(idle_since)`.

### 4.1 Parser output

```python
class ParsedLine:     name: str, quantity: int, amount_cents: Cents, taxed: bool | None,
                      confidence: float, discount_for_index: int | None
class ParsedReceipt:  merchant: str | None, purchased_at: date | None,
                      lines: tuple[ParsedLine, ...], tax_cents: Cents,
                      other_adjustments_cents: Cents, total_cents: Cents,
                      currency: str | None, warnings: tuple[str, ...]
```

### 4.2 Interpreter input

```python
class NameablePerson: person_id, names: tuple[str, ...]          # nicknames + display name
class InterpretContext:
    conversation_kind: ConversationKind, conversation_name: str | None, today: date,
    speaker_id, nameable: tuple[NameablePerson, ...], group_member_names: tuple[str, ...],
    group_names: tuple[str, ...], open_prompts: tuple[str, ...],   # short rendered questions
    draft_lines: tuple[str, ...]                                    # "1. Milk ₹60", ...
```

## 5. Orchestrator (`smartsplit.services`)

```python
class Orchestrator:
    def handle(self, message: InboundMessage) -> list[OutboundMessage]: ...
    def tick(self) -> list[OutboundMessage]: ...  # uses Clock.now()
```

- Both return messages for **any** conversation: replies to the current chat, posts to a group chat
  (a bill filed from a personal chat, draft reminders/expiry in the draft's chat), and personal-chat
  messages claimed from the `Notification` outbox (subject to opt-out, caps and the hold for people
  who haven't used the bot).
- `handle` does its LLM calls (parse, interpret, canonicalize) before taking the conversation lock.
  If saving or cancelling promotes a `queued` draft, its receipt is parsed in a second step after the
  first transaction commits, and its summary is appended to the same reply list. `tick` retries any
  draft left in `parsing` (e.g. after a crash).
- **HTTP:** the same field names in snake_case; `conversation` is `{"channel": ..., "ref": ...}`;
  images inline as `"image": {"mime_type": "image/jpeg", "data_base64": "..."}`, size-limited.

```json
POST /v1/messages
{"message_id": "wamid.123", "conversation": {"channel": "whatsapp", "ref": "1203630@g.us"},
 "conversation_kind": "group", "conversation_name": "Flat 4B",
 "sender_ref": "+919876543210", "sender_alt_ref": "123456@lid", "sender_phone": "+919876543210",
 "sender_name": "Sam", "addressed_to_bot": true, "reply_to_bot": false,
 "text": "split this, Sam paid", "image": {"mime_type": "image/jpeg", "data_base64": "..."}}
→ 200 [{"conversation": {"channel": "whatsapp", "ref": "1203630@g.us"}, "recipient_id": null,
        "text": "Toit, ₹1,200 …"}]
```

## 6. Errors

| Error | Lives in | Handled as |
|---|---|---|
| `ValueError` | pure layers, invalid input | a bug if it reaches the user; services validate first |
| `ReceiptUnreadableError` | ports | "Couldn't read that receipt, try another photo" |
| `LlmUnavailableError` | ports | "Couldn't do that, try again in a minute"; nothing changes |
| `NotAllowedError` | services | short plain refusal ("Only Sam can delete that rule") |
| `NeedsClarification` | services | becomes a `Prompt` (`which_person`, `need_contact`, …) |
