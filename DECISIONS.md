# Decisions

One line per decision: what was decided, and why. Newest at the bottom of each section.

## Made by the user (do not revisit without asking)

- Own ledger is the source of truth. A Splitwise sync may come later as an optional adapter. Why: self-hostable, no external dependency.
- WhatsApp via Baileys (unofficial) later, as a separate Node gateway calling `POST /v1/messages`, on a dedicated bot number. Not part of this build.
- Stack: Python 3.12+, FastAPI, SQLAlchemy 2 + Alembic, Postgres, uv. Why: user's preference.
- First build = the core engine with no WhatsApp (SPEC §1).
- Open source, self-hosted by others.
- (Vision review) Two ways to add bills: in a group chat (scoped to that group, like a Splitwise group) and in a personal 1:1 chat with the bot (split with people the user picks). Why: matches how people actually split.
- (Vision review) Overall balance per person across all groups and personal splits, with a per-group breakdown ("you owe Sam 50: Trip owes 80, Flat 4B owed 20, personal 10"). Why: one answer to "what do I owe X?".
- (Vision review) One currency per install (set in config), no conversion. Why: lets cross-group totals be a single number. Supersedes "one currency per group" in SPEC §3.
- ~~(Vision review) Personal-chat splits: people added are notified and the bill counts immediately; they can reply ok / details / dispute (disputed bills are flagged until the adder fixes them). People who never used the bot are not cold-messaged; the adder gets a forwardable wa.me invite, and the newcomer sees pending splits on first contact. Repeated bills to the same person are batched into one message. Why: Splitwise-like, nothing stuck in limbo, avoids WhatsApp ban risk.~~ *(superseded — P8: no disputes; see Design review below)*
- (Vision review) Picking people in a personal chat: caption ("split with Sam and Raj"), else the bot offers a numbered list of recent/frequent people and groups; unknown names → share a contact card or number; ambiguous names → bot asks. Shortcuts: "Sam paid", "Sam owes all of it", "add to <group>". Why: one-message happy path, no menus.
- (Vision review) Identity: every person must have a phone number (normalized to E.164, default country code from config); it is their unique key. Internal immutable id; chat identities (e.g. WhatsApp number, WhatsApp LID, CLI handle) stored separately, each unique and mapped to one person. Nicknames are per user ("Sam" for X, "Samuel" for Raj); own display name from their profile. No name-only people, so no merge flow. Why: simplest reliable identity; sharing a contact is two taps.
- (Vision review) Bill context is exactly one of: a group, or a personal split (added by one person in their 1:1 chat with chosen people). Personal splits have no group. Why: needed for personal chats and cross-group balances.
- (Vision review) Rules are owned, and a rule only shapes bills its owner controls. Owners/scopes: (1) the person themselves = "everywhere", created only when they state it about themselves in their personal chat; (2) a group, created by anyone stating it in that group chat or learned from answers there; (3) an adder's notes, created by stating it about someone in your personal chat or learned from your answers there, applying only to personal splits you add. Applicable rules = participants' own everywhere rules + the context owner's rules; more specific wins (group/adder notes > everywhere), then stated > learned, then newest. Transparency: summaries show who was skipped and why; anyone can list all rules about themselves and who set them. Why: one principle explains all scopes, learning follows where the answer was given, nobody's rules reach into bills they don't control.
- (Vision review) Unequal shares allowed: an override for an item may be either a list of members (equal split, as before) or a mapping member → positive integer weight ("2 yogurts for Sam, 1 for Raj", "70/30", amounts as weights). Rules stay unweighted. Approved change to the frozen §5 contract; existing acceptance tests unchanged. Why: quantity and uneven-use lines are common on real receipts.
- (Vision review) Item categories ("no alcohol" covers beer, wine): deferred, later list. Why: not needed for the first build.
- (Vision review) Editing/undoing a saved bill: any participant can ask; the bot shows the change and asks to confirm; stored as a reversing entry + a new corrected bill; all participants are notified of their new share. Why: append-only ledger, honest history.
- (Vision review) Moving out: membership gets an end date; excluded from new bills; balance stays until settled and they can still see it; that group's rules about them stop applying (their own everywhere rules are untouched). Moving in: membership starts today; only included in bills from then on.
- (Vision review) Reminders: manual only ("remind Raj" sends a nudge with the balance). No automatic reminders in the first build. Why: avoid spam and WhatsApp ban risk.
- (Vision review) History: read-only "what did I spend this month?" / "show last 5 bills".
- ~~(Vision review) Group bills: anyone in the group can answer questions; conflicting answers make the bot re-ask showing both; the adder gives the final confirm. Unanswered questions: one reminder to the adder after 24 hours; nothing is saved until confirmed. "Cancel" drops a bill still in review.~~ *(superseded — P9: latest answer wins; adder can confirm with open questions; see Design review below)*
- (Spec review) Per-item tax: the parser marks taxed lines; a pure `fold_item_tax` spreads tax over taxed lines only; if no lines are marked, tax is split like other adjustments. Why: untaxed groceries shouldn't carry someone else's alcohol tax.
- ~~(Spec review) Bot in an unknown group chat: auto-creates the group; anyone who writes becomes a member; "add Priya" adds quiet members.~~ *(superseded — P2: explicit join; see Design review below)*
- (Spec review) One bill draft per conversation; later receipts are queued.
- ~~(Spec review) Low-confidence receipt lines are flagged in the summary and must be confirmed or fixed before saving.~~ *(superseded — review: flagged, adder settles differences (P15); see Design review below)*
- ~~(Spec review) Rule deletion: everywhere rules only by the subject; group rules by any active member (subject told); notes only by their owner.~~ *(superseded — group-rule deletions are announced; see Design review below)*
- (Spec review) Timed work (24h reminders, batched notifications) runs via a `tick` entrypoint (CLI + `POST /v1/tick`) using the Clock port.
- (Vision review) Settling up against an overall balance is allocated across the groups automatically, largest debt first (oldest on ties); the user can still target one group. Why: every group's balance stays correct.
- (Design review, P1) Group bills may name a subset of current members ("me and Priya", "everyone except Raj"). Only current members; no purchase-date exception (older receipts of leavers go through personal splits).
- (Design review, P2) In group chats the bot reacts only when addressed (photos, mentions/command words, replies to it, clear answers to its prompts); silent on Unknown. Membership is explicit ("join" or being added); a non-member talking to the bot is asked to join; leavers never re-join by posting.
- (Design review, P3) Any current member can cancel a group draft at any time (bot says who); drafts get one reminder after 24h and expire after 3 days. No take-over.
- (Design review, P4) Either side can record a payment; restated + confirmed; the other side is told and can reply "not received" to reverse it; overpaying asks first; "undo last payment"; a payment said in a group chat counts for that group.
- (Design review, P5) In personal splits the payer is always the adder. "Not mine" removes you and re-splits (shown and confirmed, others told).
- (Design review, P6, P8) No disputes. Any participant can edit or delete a saved bill, with an optional reason; the bot shows the effect and asks them to confirm; everyone in the bill is told (group bills: posted in the group).
- (Design review, P7) In a group chat, balances/rules/history answers cover only that group; overall and cross-context answers go to the asker's personal chat.
- (Design review, P9) Conflicting answers: latest answer wins. The adder can confirm with questions still open.
- (Design review, P10) Membership changes take effect immediately and are announced in the group.
- (Design review, P11) "stop"/"start" for notifications and reminders; "remind" at most once per 24h per pair; daily per-person message cap.
- (Design review, P12) Likely duplicates (same group or pair, same total, within 3 days) get a warning before confirming.
- (Design review, P13) "Square up with Sam" writes offsetting entries so every context between two people clears.
- (Design review, P14) Exact amounts allowed: manual bills per person (must add up), and "Sam's part was ₹100" on a line (remainder split equally among the others).
- (Design review, P15) Review edits: change/remove/add lines, fix the total; any remaining difference is shown and the adder fixes a line or accepts it as an adjustment.
- (Design review, P16) Short summary by default; "details" shows the numbered full list.
- (Design review, P17) Item matches (raw name → key) are remembered per group, and per adder for personal splits; item keys stay install-wide so rules apply everywhere. First-time matches are shown; "that's not milk" fixes it in that scope.
- (Design review, P18) The adder can correct a number they gave for someone, only while that person has never used the bot. Leaving the group chat ends membership.
- (Design review, P19) Three rule kinds only; "Raj drinks milk now" deletes the rule in that scope.
- (Design review, P20) Discount lines the parser links to an item share that item's key; unlinked discounts are shared by everyone.
- (Design review, P21) History and "this month" use the purchase date; timezone from config; "what did I spend" = my shares.
- (Design review, P22) "Forget me" is specified (SPEC §13) but built later.
- (Design review, P23) The invite text for a non-user is given only on the adder's first bill with them.
- (Design review, P24) Adjustments are weighted by member subtotals clamped at 0; split equally only when every clamped subtotal is 0.


## Made by Claude during the build

- (M0) Money as integer cents, with exact Fractions inside the split engine, and largest-remainder rounding with ties broken by member order. Why: deterministic and always sums exactly to the receipt total.
- (Spec review) No Channel port: use-cases return the OutboundMessages to deliver (including notifications to other people's personal chats, via a Notification outbox); entrypoints hand them on. Added an IdGenerator port so services stay deterministic in tests. Why: simpler, fully testable.
- (Spec review) Summaries show the reason for group rules and the adder's notes, but only "skipped" for someone's Everywhere rule. Why: personal facts shouldn't leak into other groups.
- (Spec review) Settle-up overpayment beyond what A owes B is recorded in the personal-splits context. Why: never lose money, no error for the user.
- (M0) Layering enforced by import-linter in `scripts/check.sh`. Why: stops long autonomous runs from eroding the architecture.
- ~~(M1 prep, user-approved) Adjustments are weighted by item subtotals clamped at 0; if the raw subtotals sum to ≤ 0, or all clamped weights are 0, split equally. Why: nobody gets paid via tip because a discount was assigned to them, and SPEC's "discount cancels everything → equal" still holds.~~ *(superseded — P24: only "all clamped 0 → equal"; see Design review below)*
- (M1 prep, user-approved) Rules about members not in the split are ignored. Why: someone who left must not strip an item from everyone.
- (M1 prep, user-approved) Override for an unknown item id, or an empty override, raises ValueError; a member repeated in a list override counts once. Why: these are caller bugs, fail loudly.
- (M1 prep, user-approved) Duplicate item ids raise ValueError. Why: assignments and questions are keyed by item id.
- (M1 prep, user-approved) Conflicting rules for one member/key follow §5 order: `only` beats `exclude`/`soft_exclude`; no soft-rule question when `only` applies. Why: already implied by the spec's step order.
- (M1 prep, user-approved) Negative shares round with the same floor + largest-remainder rule. Why: one rounding rule, always sums exactly.

- (M1) The frozen engine types and `split_receipt` moved verbatim from `engine/__init__.py` to `engine/split.py`, re-exported from `smartsplit.engine`. Why: the package is split into modules (split, tax, exact, rounding) without circular imports; the public contract is unchanged.
- (M1) One rounding helper, `round_preserving_total`, serves both `split_receipt` and `fold_item_tax`. Why: one floor + largest-remainder rule everywhere.
- (M1) `amounts_to_weights` follows the CONTRACTS signature (`fixed` as (person, cents) pairs, returns `Weight`s). Weights are scaled by the number of others and reduced by their gcd, so fixed people get exactly their amount. If the fixed amounts use the whole line, the others are left out (weights must be positive). No fixed amounts, a person listed twice, or a line ≤ 0 raise ValueError. Why: exact, and keeps the weight invariant.
- (M1) A bare string as an override raises ValueError. Why: a `str` is a `Sequence[str]` and would silently split by letters.
- (M1) CI uses `actions/checkout@v7` and `astral-sh/setup-uv@v7` (both Node 24). Why: GitHub deprecated Node 20.

- (M2) Domain split into `enums.py`, `values.py`, `model.py`, `messages.py`, `commands.py`, `prompts.py`, `phone.py`; `smartsplit.domain` re-exports only the most used names. Command fields with natural defaults (empty tuples, None) have them, so required fields come first (`Edit.op` before `target`, `AddRule.item`/`kind` before `subject`, `RecordPayment.amount` before `payer`/`payee`); `NotThisItem.item_said` is optional (None = no item named). Edit operations live in `domain/edits.py`. Why: readable construction in services, tests and the fake interpreter; field names are as agreed.
- (M2) Port errors are `ReceiptUnreadableError` and `LlmUnavailableError` (CONTRACTS said `ReceiptUnreadable`/`LlmUnavailable`). Why: ruff N818 requires the `Error` suffix; renaming beats suppressing a lint rule.
- (M2) Store method lists finalized for what M3 needs plus CONTRACTS' special queries; later milestones add queries as they need them (e.g. "held notifications for a person", "bills by adder"). Why: no speculative methods. `due_for_reminder_or_expiry(idle_since)` takes the cutoff, so the 24h/3-day policy stays in services.
- (M2) `UnitOfWork` exposes its stores as read-only properties. Why: Protocol attributes are invariant in mypy; properties let implementations return their concrete stores.
- (M2) Postgres adapter uses SQLAlchemy Core tables mapped by hand to the frozen dataclasses (no ORM); nested value tuples (lines, overrides, payloads, answers, replies) are tagged JSONB through a small codec; participants and bill ids are text arrays (GIN index for "bills I'm in"); scopes are (scope_kind, scope_ref) with '' for Everywhere; a null context_group_id is the personal context; `seq` identity columns break timestamp ties. Why: simple, explicit, and the frozen domain stays free of persistence concerns.
- (M2) The conversation lock is `pg_advisory_xact_lock` on a blake2b hash of the length-prefixed (channel, ref). Why: released automatically at commit/rollback; length prefix avoids collisions between e.g. ("a", "b\0c") and ("a\0b", "c").
- (M2) Alembic runs programmatically (`adapters/db/migrate.py`, no root alembic.ini); a test asserts the migrations match the table definitions. Why: one less config file for self-hosters; the CLI gets a migrate command in M9.
- (M2) Repository contract tests run every case against the in-memory fake and real Postgres. The Postgres schema is rebuilt from the migrations once per session and all tables are truncated before each test. Why: proves the fake behaves like the database; truncation gives each test a clean schema at a fraction of the cost of re-migrating.
- (M2) The in-memory repository deep-copies state per unit of work and commits by swapping. Why: real rollback semantics in unit tests.
- (M2) Added the `pydantic.mypy` plugin to `[tool.mypy]`. Why: without it mypy thinks `Settings()` needs every required field as an argument (pydantic-settings fills them from the environment); the plugin adds pydantic-aware checking and loosens nothing else.
- (M2) `config.Settings` validates the shape of currency (three capital letters) and region, timezone (zoneinfo) and numeric limits at startup; `invite_template` has a neutral default (operators set their wa.me link). Why: misconfiguration fails fast.
- (M2) `FileImageStore` names files `<uuid hex><ext>` and refuses refs that aren't a plain file name. Why: an image_ref from the DB can never escape the image directory.

- (M2 review) `claim_due` filters held and already-capped recipients in SQL and locks at most `limit` rows (`FOR UPDATE SKIP LOCKED`); a batch that would push one person past the cap drops the extra rows (they wait for the next tick). Two concurrent claimers can still exceed one person's cap slightly, because each counts only committed sends. Why: no backlog of held rows gets locked or starves others; `tick` normally runs one at a time, so the small cap race is accepted.
- (M2 review) `DraftStore.update(draft, expected_state)` writes only if the draft is still in that state, else `StaleDraftError` (port error). Why: SPEC 12.2 "draft state changes are conditional on the expected current state" (e.g. `tick` expiring a draft while "yes" is handled).
- (M2 review) Every Postgres unit of work runs `SET LOCAL TIME ZONE 'UTC'`. Why: CONTRACTS requires UTC datetimes; a server in another zone would otherwise return local offsets.
- (M2 review) `DATABASE_URL` is a `SecretStr`. Why: it usually contains the DB password.
- (M2 review) The codec fills missing fields from their dataclass defaults. Why: adding a defaulted field to a command later must not break prompts already stored.

- (M3) `match_item` checks this place's aliases before an exact key match. Why: an alias records what people here said ("that's not milk"), which must beat the raw name.
- (M3) A model answer equal to the line's own normalized name means "new item": it becomes a known key, is not stored as an alias and is not shown as a new match. Fuzzy and other model matches are stored as aliases and marked `match_is_new`. The model is asked at most once per distinct name per receipt.
- ~~(M3 review) Unlinked discounts stay unkeyed and are split among all participants.~~ *(superseded — Checkpoint A: refunds are matched by name; only a negative line with a valid `discount_for` is a linked discount, which takes its line's key and override and is never sent to the model. `propagate_discount_overrides` is back to the CONTRACTS signature.)*
- (M3) Services depend on a narrow `Canonicalizer` port for matching; `CommandInterpreter` extends it. The M3 fake is `FakeCanonicalizer` (a table, else the normalized name); M6 builds the full fake interpreter. Why: matching needs only canonicalize.
- (M3) Learning records at most one observation per (person, item key) per bill (disagreeing lines count as `included`), attributes learned rules to the bill's adder, and leaves an identical learned rule untouched. Why: two milk lines on one receipt must not teach a rule alone; "who set it" needs an author.
- (M3) Stated-rule and deletion permissions (SPEC §6.2) live in `services/rules.py`: Everywhere only by the subject, group rules by current members, notes by their owner; violations raise `NotAllowedError` (CONTRACTS' `NotAllowed`, renamed for ruff N818). Adding a group rule also needs current membership. Why: non-members are asked to join first.
- (M3) `resolve_rules` breaks exact-timestamp ties by rule id. Why: deterministic.

- (M3 review) SPEC §6.2 "a group cannot override someone's everywhere rule" is read as "can't delete or change it": on a group bill the group's own rule for that person still wins (§6.3, F7). The learning/match scope follows the bill's context (`local_scope_for`), so a bill filed into a group from a personal chat learns in the group. Why: §6.3 and F7 are explicit; a filed bill is a group bill.
- (M3 review) `match_lines` reports `model_calls` so the orchestrator can count them against the per-person daily limit. Why: SPEC §12.2.

## Made by Claude (design review, technical)

- Group balance (incl. settlements) is the source of truth inside a group; who-owes-whom there = `simplify_debts`; personal splits use raw pairs; overall = sum. Why: one consistent model; following the bot's advice can't corrupt the overall view.
- `BillLine` stores each saved line's assignees and weights; `AnswerObservation` feeds learning; `Prompt` (with kinds) replaces `PendingQuestion`; `ProcessedMessage` gives idempotency. Why: details/edits, learning and restart-resume need persisted data.
- `fold_item_tax` takes `TaxedLine(item, taxed)` and weights by taxed amounts clamped at 0; `amounts_to_weights` turns exact amounts into weights. Both pure, in engine, built in M1. Why: no blow-ups with negative taxed lines; keeps the frozen engine contract.
- `simplify_debts` is described as greedy (few transfers), not minimal. Why: greedy isn't minimal (+6,+4,−4,−3,−3).
- `phonenumbers` for E.164 normalization (pure, allowed in domain). Why: country trunk prefixes are not safe to hand-roll.
- Safety: shared API token on `/v1/*`; idempotent `message_id`; per-conversation advisory lock + unit of work; LLM calls outside the lock with timeouts; `tick` claims with SKIP LOCKED, at-most-once delivery; model output is only a proposal and money-moving/destructive commands need a deterministic restatement + "yes"; no message bodies/phones in logs. Why: proportionate protection for a self-hosted bot.

- Purity enforced with ruff banned-api (clock, uuid, random, secrets, logging, os.environ outside adapters/entrypoints/config/tests) plus DTZ and FIX rules; import-linter contracts added for DB libs, web/CLI frameworks, adapter independence and settings. mypy now checks tests. Why: the spec's layer and purity rules are only real if the build enforces them.
- (User-approved) CI on GitHub Actions runs scripts/check.sh against Postgres and fails if frozen files change; a SessionStart "compact" hook reminds the agent to re-read the docs; CLAUDE.md names the working branch. Why: independent enforcement of the gate and the frozen files.
- Milestone boundaries are recorded as commit hashes in the PROGRESS log, not git tags. Why: this environment can't push tags.

## Contracts review (2026-11-23)

- (User) Learning may upgrade a stated `soft_exclude` to a learned `exclude`/`only`; stated `exclude`/`only` are never overridden by learning.
- (User) Someone who moves out is removed from open drafts in that group; the draft is re-split and shown again.
- (User) Draft reminders and expiry notices go to the draft's chat (the group chat for group bills).
- Messages and the `Command` union live in `domain` (with typed prompt payloads and effects), so entities like `ProcessedMessage` and `Prompt` can reference them without breaking the layers. Why: import-linter.
- Value objects hold no dicts: per-person data is tuples of `Share`/`Weight`/`ExactAmount`. Why: frozen dataclasses with dicts are unhashable and still mutable.
- `BillDraft` holds a working copy of the receipt for review edits; `Receipt` stays the immutable parse record; `Bill` stores tax and adjustments and `BillLine` keeps position, quantity, taxed and discount link. Why: edits and "details" must rebuild exactly.
- `confirm_action` prompts store the command and its exact effect plus a version; "yes" applies it only if nothing changed. Why: what is restated is what happens (SPEC §12.3), and it survives restarts.
- One `Edit(target, op, reason)` command with typed ops replaces EditDraft/EditBill; `AnswerPrompt` has typed slots (yes, choice, people); `Acknowledge` for "ok"; `AddPerson` covers adding members in groups. Why: unambiguous for both the model and the regex fake.
- `handle`/`tick` return messages to any conversation; the Notification outbox is only for personal-chat messages subject to holds and caps; `requested_reply` kind for "sent you a DM". Why: filing into groups, group reminders and DM answers need it.
- New `ImageStore` port with a filesystem adapter (`adapters/files`). Why: services may not do file I/O; queued drafts must reload their image.
- `ConversationKey(channel, ref)` everywhere; `InboundMessage` gains `conversation_name` and `sender_alt_ref`. Why: group names come from the chat; linking a WhatsApp hidden id to a number.
- Duplicate check runs after parsing and includes other open drafts. Queued drafts are parsed after the first transaction commits (and `tick` retries stuck ones). Why: needs the total; no model calls inside the lock.
- Added `phonenumbers` dependency (pure E.164 parsing). Why: see the identity decision above.

- (User) CONTRACTS.md v2 agreed; build runs in a fresh session, M1 → M3 straight through, stopping at CHECKPOINT A.

## M5 — receipt parsing

- (M5) Added dev dependency `pytest-socket`; pytest runs with `--disable-socket --allow-hosts=127.0.0.1,::1,localhost`, and the one live test opts back in with `@pytest.mark.enable_socket`. Why: "no network in tests" is enforced, not just intended (design review E11); local Postgres stays reachable.
- (M5) The parser uses structured output (`output_config.format` with a JSON schema) on `messages.create`, one vision request per attempt, the model and `max_tokens` from config, and the SDK's own retries off (`max_retries=0`) so the spec's "retry once" is exact: an API error or invalid output gets one more attempt; a 400 (image refused) or an unsupported image type is unreadable at once. A refusal or a cut-off answer counts as invalid output. Why: SPEC 7; structured output is the documented way to get JSON back now that forced tool choice 400s on current models.
- (M5) No server-side refusal `fallbacks` on the receipt call. Why: the model is operator-configured and the fallback parameter is model-specific; a refusal on a receipt photo just means "couldn't read that, try another photo".
- (M5) Model output is validated in `services/receipt_output.py`, shared by the Anthropic adapter and `FakeReceiptParser`: integer cents only (12.5 refused, never rounded), quantity ≥ 1, non-empty names, at most `max_lines` lines, total > 0 are hard failures; confidence is clamped, an impossible discount link or date becomes None, NUL characters are dropped; a total that doesn't add up and a foreign currency become warnings. Why: SPEC 7, and NUL can't be stored in Postgres (Checkpoint A follow-up).
- (M5) Fixtures in `tests/fixtures/receipts/*.json` are hand-written in the exact structured-output shape (there is no API key here to record real answers); `FakeReceiptParser` treats image bytes as such a recorded answer, so the CLI demo can use the fixture files as "photos". The live test uses a rendered receipt image (`live_cafe_receipt.png`, made-up shop) with known totals.

- (M5 review) A 400 about the image (or an unsupported image type) is "unreadable, try another photo" with no retry; any other 400 is a setup problem, reported as `LlmUnavailableError` ("try again in a minute"). `image/jpg` and any letter case are accepted. Why: a misconfigured model must not tell users to retake photos forever.
- (M5 review) Defaults: `SMARTSPLIT_LLM_MAX_TOKENS` 16000 (a 150-line receipt needs about 6,000 tokens plus thinking) and `SMARTSPLIT_MAX_IMAGE_BYTES` 5 MB (the API's image limit). Why: the old defaults made long receipts and normal phone photos fail.
- (M5 review) Receipt validation also refuses amounts above 10^12 cents and quantities above 10^6, keeps a currency only if it is a 3-letter code, drops a discount link from a non-negative line, and shows amounts in warnings as money (`domain/money.format_cents`). The request schema lives with the Anthropic adapter. Why: model output reaches the database and chat text.

## M6 — command interpreter

- (M6, corrected in review) One tool per command (29), **not strict**: strict structured output allows at most 20 strict tools and 16 union-typed parameters per request (documented limits; over them every call would 400). Schemas generated from the command dataclasses (`adapters/llm/tool_schemas.py`): every field required, optional ones nullable, union variants tagged with `type`, so a tool call decodes with the domain codec (moved from `adapters/db` to `domain/codec.py`, as both adapters need it and it is pure). Fixed tool order and a cached system prompt keep the prefix cacheable. Why: SPEC 8; one decoder for DB rows and model output.
- (M6) `tool_choice` stays `auto` (forced `any`/`tool` returns 400 on current models); no tool call, a refusal, or a call that doesn't decode is `Unknown`. API errors get one retry, then `LlmUnavailableError`. Effort `low` for interpretation and canonicalization. Why: documented current API; these are short, latency-sensitive classifications.
- (M6) `canonicalize` uses structured output `{"item_key": ...}`; unusable output falls back to the normalized name (a new item), never an error. Why: matching must not fail a whole receipt over one line.
- (M6) `services/command_checks.check_amounts` refuses any amount (incl. inside edits and exact amounts) that isn't > 0 and < `SMARTSPLIT_MAX_AMOUNT_CENTS`, and weights, list numbers and counts outside 1–1000; the orchestrator (M7) must call it on every interpreted command. Why: SPEC 8 / 12.3, model output is a proposal.
- (M6) `KeywordInterpreter` (fakes) covers the USE_CASES phrases with ordered regexes; "Sam paid" while a draft is under review is a payer edit, otherwise a new split; weights or an exact part without a line name apply to a one-line bill only. Speaker convention: where CONTRACTS says None means the speaker, "I"/"me" become None; elsewhere names stay as said and services resolve "me". Why: tests and the CLI demo need deterministic commands.
- (M6 review) The model sees the context by names only (no person or speaker ids); the message is JSON-escaped inside its tag; an `Unknown` call always keeps the original text; `AnswerPrompt.prompt_id` from the model is dropped; only network errors, 408/409/429 and 5xx are retried; enum/literal values match case-insensitively (the docs don't guarantee casing). Why: SPEC 12.3 and the documented structured-output behaviour.

## M7 — orchestrator I

- **Answers:** a bare "yes" with only line questions open is a confirm (only the adder; G4/G5). Any other open prompt (duplicate warning, restated action, who-with, which-person, need-contact, total, join) is a direct question and takes the answer first, newest first.
- **Question batches:** line questions are numbered by their place in the batch ("2 no", "1: Sam and Raj"). A question stays in its batch after an answer, so a later answer replaces it (G3); the next batch opens when every question in the batch has an answer.
- **Group chats:** a message not addressed to the bot is only read when a prompt is open there, and only counts if it is an answer; everything else (and `Unknown`) gets no reply. A photo is always a receipt to split; its caption says with whom.
- **Refusals roll back:** a `NotAllowedError`, `NeedsClarificationError` or bad amount undoes the handler's writes; the message is then recorded with only the refusal (or the which-person / need-contact prompt). A model outage records nothing, so the gateway's retry works.
- **Model calls are counted** in the turn's transaction (interpret: 1; a receipt: 1 + canonicalize calls, charged to the adder). A receipt the model couldn't read because it was down stays in `parsing` for `tick` to retry (M8).
- **Rules about others** (stated or deleted) are restated with a `confirm_action`; rule effects carry version 0 (a "yes" re-applies exactly the rule shown). Your own rules apply at once.
- **Privacy:** in a group, balances answers cover the group; the wider answer is DM'd only when the asker has something open elsewhere, and only if they have a personal chat.
- **Small rules:** a typed personal bill with nobody named asks "who's this with?" like a photo; an edited line amount is no longer flagged as unclear; the speaker can be named by their own name; if the payer leaves, the adder pays; at most `max_queued_drafts` receipts wait; overall balances list the largest first.
- **Tests:** `tests/integration/` drives the whole bot through `Orchestrator.handle` on the in-memory fakes, by use case; `test_on_postgres.py` runs a tour of every prompt and two simultaneous confirms on real Postgres.

## Checkpoint A review (2026-11-23)

- (User) Unlinked negative lines (refunds) are matched by name and follow that item's rules; generic coupons that match nothing stay shared by everyone; discount-link treatment needs `discount_for` and a negative amount.
- (User) Exact amounts ("Sam's part was ₹100") are before tax and tip; that person also pays their share of the line's tax and the tip.
- Someone removed from a weighted line counts as `excluded` for learning; people on it count as `included`.
- Full findings and fix list: docs/CHECKPOINT_A_REVIEW.md.
- (Fix) Port-level `DuplicateKeyError`, `MissingReferenceError` and `InvalidRecordError` (all `ConstraintViolationError`); Postgres integrity errors are translated by SQLSTATE at the unit-of-work boundary, and the fake checks the same keys, foreign keys and checks. Why: services and tests see one error type whichever backend runs.
- (Fix) `claim_due` takes a constant transaction-level advisory lock, so claims run one at a time and the daily cap holds under concurrency (supersedes the "small cap race accepted" note). Why: Checkpoint A must-fix.
- (Fix) `RuleStore.put` is one `INSERT … ON CONFLICT DO UPDATE`; at most one active draft per chat is a partial unique index (migration 0002) and a fake check. Why: concurrent writers can't collide or create two active drafts.
- (Fix) `add_stated_rule`/`delete_rule` derive the scope from (chat kind, group, speaker, subject); the only permission left to check is current group membership at `now` (joined, not yet left). Why: a group chat can never write someone's Everywhere rule, and nobody can write another's notes.
- (Fix) Keys the model creates count as known for the rest of the receipt. Why: near-duplicate lines cost one model call.
- (Fix) Empty `ANTHROPIC_API_KEY`/`SMARTSPLIT_API_TOKEN` load as unset; `fuzzy_threshold` must be ≥ 1; the invite default matches `.env.example`. Why: a copied `.env` behaves as expected; threshold 0 matched empty names to anything.
- (Fix review) Postgres constraint errors are translated to port errors at each store call (and again at commit), so both backends raise `DuplicateKeyError` etc. at the same moment; storage errors live in `ports/errors.py`. On Postgres the error also aborts the transaction, so callers catch it outside the unit of work. Why: parity between fake and Postgres.
- (M4) Payments are allocated per context: "what A owes B" is the sum of contexts where A owes B, not
  netted across contexts (netting is what square-up is for). A payment in a named context (said in a
  group chat, or "for the trip") stays there entirely, overpayment included, as a credit in that
  context; the overpaid amount is returned only so the bot can restate it (SPEC 10.6). Ties after
  "oldest bill between the two" go by input order; bills that were deleted (reversed) don't count. Why:
  SPEC 9 "recorded in a group chat → that group"; each context's balance stays the truth.
- (M4) Square-up settles each group until its greedy plan shows nothing between the two (the loop ends:
  each round shrinks |balance(a)| + |balance(b)|), then one personal row in the opposite direction.
- A learned rule is only undone by stating or deleting a rule; later `included` answers just stop a new streak. Why: simple and predictable; the summary shows learned rules.

## Open (waiting for the user)

- **Square-up when a group's greedy plan reshuffles (M4 review).** SPEC §9 asks for two things: every
  context's amount between A and B becomes 0, *and* the overall net moves into personal splits with
  rows that net to zero. Usually both hold. But a group shows A–B through its greedy plan, and settling
  the shown amount can reshuffle the plan, so clearing it fully can take slightly more than was shown
  (about 1.5% of random groups; e.g. shown 15, settled 19). Then rows that net to zero leave an overall
  view of 19, not 15. Options:
  - **(a, recommended, built now)** Keep rows netting to zero: nobody's real money changes, and the
    confirm step restates the exact effect ("afterwards you owe Sam ₹190 in personal splits").
  - (b) Put the pre-square-up net (15) into personal splits; the rows then don't net to zero, so real
    balances shift by the difference.
  - (c) Settle only the amount shown in each group (one round), accepting that a group may still show
    a small A–B amount afterwards.
  Reversible; (a) is implemented and tested (everyone's total across contexts is unchanged).
