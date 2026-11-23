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

## Open (waiting for the user)

(none)
