# Use case → contracts trace (against CONTRACTS.md v1)

Independent traceability check of every use case in USE_CASES.md against the first draft of
CONTRACTS.md (2026-11-23). Every GAP and UNCLEAR below was fixed in CONTRACTS.md v2 and SPEC.md
(see DECISIONS.md, "Contracts review"). Kept as a record; re-run the trace if the contracts change a lot.

# SmartSplit use-case traceability (USE_CASES.md -> CONTRACTS.md draft)

Sources: docs/USE_CASES.md, docs/CONTRACTS.md (DRAFT), docs/SPEC.md, src/smartsplit/engine/__init__.py.
Inbound is the `InboundMessage` (IM) unless noted. "Out" = OutboundMessage returned by `handle`/`tick`.
"N(kind)" = a Notification row. "P(kind)" = a Prompt row. Gap ids (G-x) and unclear ids (U-x) are listed at the end.

| id | command | logic | data | outbound | status | note |
|---|---|---|---|---|---|---|
| A1 | none: first personal IM (sender_ref, sender_phone, sender_name); Help implied | none | W Person(display_name, phone, has_used_bot=true), ChatIdentity, Conversation(personal, person_id); R held Notifications(person_id, sent_at=None) | speaker: welcome + help + held items | OK | Needs a "claim held for person" query beside claim_due (M2 finalizes queries). |
| A2 | none (group IM, unknown conversation_ref) | none | W Group(name, channel_ref), Conversation(group), Membership(position 0) | group: "reply join" | GAP | G-2: IM has no chat title, so `Group.name` has no source over the API. |
| A3 | JoinGroup(person=None) | none | W Membership(position=max+1, joined_at) | group: announcement | OK | |
| A4 | none: non-member IM -> P(join_group) | none | W Prompt(join_group, payload{person}) | group: "join splits here?" | GAP | G-3: Prompt has no field saying only that non-member may answer. |
| A5 | AddMember(person) or AddPerson(name, phone) + IM.contact | normalize_phone | W Person, Nickname(owner=speaker), Membership | group: announcement | UNCLEAR | U-1: AddMember has no phone; "add Priya 98765..." typed in text can't be carried by AddMember, and which command a group "add Priya" maps to is undefined. |
| A6 | none | none | ChatIdentity(channel, external_ref) many -> one Person | none | OK | |
| A7 | none: IM with sender_phone=None | none | R ChatIdentity; later W ChatIdentity(lid) on 1:1 | sender: "message me 1:1 first" | UNCLEAR | U-2: linking needs one IM carrying both hidden id and number; IM has one sender_ref, and IM.channel ("whatsapp") vs ChatIdentity.channel ("whatsapp_lid") mapping is undefined. |
| A8 | any with phone | normalize_phone | Person.phone E.164 unique | none | OK | |
| A9 | SetNickname(person, nickname); resolution via InterpretContext.nameable | none | Nickname(owner, subject, name) | none | OK | |
| A10 | any with PersonRef -> NeedsClarification -> P(which_person) | none | W Prompt(which_person, payload{candidates, pending command}) | speaker: "Sam from Flat 4B, or Sam K?" | GAP | G-2 (group name for the label) and U-3 (payload must hold the pending command; no schema). |
| A11 | any with unknown PersonRef -> P(need_contact); answer = IM.contact or text | normalize_phone | W Prompt(need_contact, payload{name, pending command}) -> Person, Nickname | speaker: ask for card/number | UNCLEAR | U-3: pending command stored in untyped payload. |
| A12 | CorrectNumber(person, phone) | normalize_phone | R Person.has_used_bot; W Person.phone | speaker | GAP | G-8: nothing records which speaker supplied the number. |
| A13 | n/a (rendering) | mask_phone | Nickname for viewer, Person.display_name | all | OK | |
| B1 | none or interpret() when open prompts | none | R Prompt(open) | none in groups for Unknown | UNCLEAR | U-4: IM.reply_to_bot doesn't say which bot message, OutboundMessage has no id, and the rule for "clearly answers" isn't defined. |
| B2 | MemberLeft(person) or IM.event(participant_left, subject_ref) | none | W Membership.left_at; R ChatIdentity for subject_ref | group: announcement | OK | Leaver stays in ContextLedger.member_order. |
| B3 | same as B2 | resolve_rules (non-participant rules ignored) | W Prompt.status=dropped for his engine_questions; cancel drafts where added_by=leaver | group | UNCLEAR | U-5: does the leaver stay in an in-review draft's participants snapshot? Finding "his" prompts means querying untyped payload. |
| B4 | JoinGroup | none | new Membership | group | OK | |
| B5 | StartSplit / AddManualBill | none | BillDraft.participants snapshot at creation | none | OK | |
| B6 | ShowBalances | balances, overall_between | ContextLedger per context | speaker | OK | |
| C1 | none (photo) or StartSplit from caption | parse -> match_item -> fold_item_tax -> resolve_rules -> split_receipt | W BillDraft, Receipt, P(engine_question{item_id, member_id, reason}) | group: summary | GAP | Summary needs G-6 (scope of the winning rule) and G-7 (first-time match); otherwise traceable. |
| C2 | StartSplit(people/everyone/except_) or AddManualBill(people,...) | none | BillDraft.participants | group | OK | |
| C3 | StartSplit(payer) | none | BillDraft.payer_id | group | OK | |
| C4 | AddManualBill(description, amount, everyone, purchased_on) | split_receipt | BillDraft.manual_lines | group: summary | GAP | G-1: BillDraft has no description or purchased_at, so "electricity" and "yesterday" can't be kept until save. |
| C5 | EditDraft(set_amount) or AnswerPrompt to P(confirm_total) | split_receipt(adjustments incl. accepted difference) | Receipt.warnings; accepted difference: nowhere | group: diff | GAP | G-1: nowhere to store the accepted difference or edited lines (Receipt is frozen; the draft has only manual_lines). |
| C6 | EditDraft(set_amount/add_line/remove_line/set_total, line) | re-split | edited lines and total: nowhere | group: summary again | GAP | G-1 (same). Line numbering also needs a stable working line list. |
| C7 | none | threshold on LineItem.confidence | LineItem.confidence; P(confirm_line) | group | OK | |
| C8 | ShowBillDetails(bill=None) while reviewing | none | Receipt lines | group | OK | Assumes bill=None during review means the draft. |
| C9 | none | ReceiptParser raises ReceiptUnreadable | BillDraft -> cancelled | group | OK | |
| C10 | none (2nd photo) | parse later | W BillDraft(state=queued) | group: "after the Toit bill" | GAP | G-1: a queued draft has no image_ref or mime_type (Receipt only exists after parsing). Also undefined: when the queued parse runs, given that LLM calls happen outside the lock. |
| C11 | none -> P(duplicate_warning) | find_likely_duplicate(total, purchased_at, people, recent bills) | R Bill | group | UNCLEAR | U-6: the flow puts the duplicate check before parsing, but it needs the parsed total. It only checks saved Bills, so a simultaneous upload by Sam (still a draft) is missed. |
| C12 | CancelDraft | none | BillDraft.state=cancelled | group: "Sam cancelled" | OK | Canceller only needed in the reply. |
| C13 | none (tick) | drafts.due_for_reminder_or_expiry(now) | BillDraft.last_activity_at, reminded_at | adder: reminder/expiry | UNCLEAR | U-7: sent to the draft's chat or the adder's DM? No NotificationKind for draft reminder/expiry, so it bypasses opt-out/caps. |
| C14 | none | ParsedReceipt.currency vs config | Receipt.warnings | group | OK | |
| C15 | ConfirmDraft | balances, simplify_debts | W Bill, BillLines | group: summary + balances | OK | |
| D1 | StartSplit(people) from caption | as C1 | BillDraft(PersonalContext, payer=speaker) | speaker | OK | |
| D2 | none (photo, no caption) -> P(who_with) | recent/frequent from Bills + Memberships | BillDraft(awaiting_people) | speaker: numbered list | GAP | G-1: the image must be kept until the answer, and the draft has no image_ref. U-3: options in untyped payload. |
| D3 | StartSplit(owes_all) | overrides on every line | none | speaker | GAP | G-1: owes_all must survive until lines exist (after parsing), and BillDraft has no field for it. |
| D4 | StartSplit(payer) in personal | NotAllowed | none | speaker: refusal | OK | |
| D5 | FileIntoGroup(group_name) | resolve_rules for the group | BillDraft.context changes | personal: questions; group: saved summary | UNCLEAR | U-8: participants on filing (keep named or all members?) are undefined. Posting into another chat conflicts with SPEC 2 ("current chat" or Notification). Also needs G-2. |
| D6 | ack "ok" / ShowBillDetails / NotMine / EditBill | overall_between at render | N(bill_added, bill_ids) | Sam DM at tick | UNCLEAR | U-9: no Command for "ok". Replies must find the bill from the last notification (see G-9). |
| D7 | ConfirmDraft | "first bill with her" = no earlier Bill with added_by=me and Priya in participants | N(bill_added) held; Person.has_used_bot=false | adder: invite text | OK | Derivable from Bill; needs a bills query (M2). |
| D8 | none (first IM) | render held N | Notification sent_at=None; Bill.added_by gives "Thanoo" | Priya | OK | |
| D9 | ConfirmDraft x3 | combine at claim | 3x N(bill_added) | Sam: one combined numbered message | GAP | G-9: nothing records the numbering Sam was shown, so "details 2" can't be resolved later. |
| E1 | n/a | split_receipt | | | OK | |
| E2 | n/a | split_receipt (exclude) | Rule | | OK | |
| E3 | n/a | split_receipt (only) | Rule | | OK | |
| E4 | n/a | split_receipt (only x2) | Rule | | OK | |
| E5 | n/a | split_receipt -> Question(SOFT_RULE) | P(engine_question) | | OK | |
| E6 | AnswerPrompt for NO_ELIGIBLE_MEMBERS | split_receipt | P(engine_question) | | OK | Answer naming people is weakly typed (see U-10). |
| E7 | EditDraft(assign, weights) | split_receipt weighted override | BillDraft.overrides | | OK | |
| E8 | EditDraft(assign, exact) | amounts_to_weights | overrides | | OK | |
| E9 | AddManualBill(exact) | amounts_to_weights (others empty) | overrides | asks if sum differs | OK | |
| E10 | n/a | split_receipt | LineItem negative, discount_for=None | | OK | |
| E11 | n/a | match discount_for -> same canonical key | LineItem.discount_for | | UNCLEAR | U-11: shared via rules only. If the milk line has an override (an answer/edit), the linked discount line doesn't follow, because overrides are per line id. |
| E12 | n/a | fold_item_tax + adjustments | Receipt.tax/other_adjustments | | OK | |
| E13 | n/a | fold_item_tax | LineItem.taxed | | OK | |
| E14 | n/a | fold_item_tax leftover | | | OK | |
| E15 | n/a | split_receipt clamp | | | OK | |
| E16 | n/a | split_receipt | | | OK | |
| F1 | AddRule(subject=None) in personal | normalize/match item | W Rule(Everywhere, stated, author) | speaker | OK | |
| F2 | AddRule in group | | Rule(GroupScope) | group | OK | |
| F3 | AddRule(subject=Sam) in group -> P(confirm_action) | | Rule(GroupScope) | group | OK | Payload untyped (U-3). |
| F4 | AddRule(subject=Sam) in personal | | Rule(NotesScope(owner)) | speaker | OK | |
| F5 | ConfirmDraft | observations -> learned_kind | W AnswerObservation, Rule(learned) | group | UNCLEAR | U-12: if "Sam usually skips chips" was stated in Flat 4B (a GroupScope soft_exclude), a learned rule can't replace it (one rule per scope+subject+key; learned never replaces stated), so the bot keeps asking. |
| F6 | ConfirmDraft (personal) | same | NotesScope(adder) | | OK | |
| F7 | n/a | resolve_rules | Rule.scope/source/created_at | | OK | |
| F8 | n/a | resolve_rules(added_by) | | | OK | |
| F9 | DeleteRule(subject, item) | | Rule delete in chat's scope | | OK | |
| F10 | n/a | match_item(raw, aliases, known_keys, threshold), canonicalize | ItemAlias; known keys: ? | | GAP | G-12: SPEC 4.3 has an install-wide `Item` set, but CONTRACTS has no Item entity or `items` store, so known_keys has no source. |
| F11 | n/a (summary) | Match.how | ItemAlias/LineItem don't record match novelty | summary | GAP | G-7: nothing records that a match is new, so after a re-render or restart "shown once" can't be decided. |
| F12 | EditDraft(not_this_item, line) | | W ItemAlias replace | | UNCLEAR | U-13: what key the line gets after "that's not milk" (its own normalized name? re-ask the model?) is undefined. |
| F13 | ListRules(subject=None) in personal | | R Rule by subject | speaker | OK | |
| F14 | ListRules in group | | | group: group rules; DM: full list | GAP | G-5: no way to send an asked-for DM (no NotificationKind; SPEC 2 forbids non-current-chat Outbound). |
| F15 | DeleteRule | permission by scope | Rule.author_id, scope, Membership | group: announcement | OK | |
| F16 | n/a (summary) | resolve_rules -> RuleInput | RuleInput has no scope | summary | GAP | G-6: resolve_rules drops which scope won, so the summary can't hide the reason for an Everywhere rule. |
| G1 | n/a | questions -> batches of 3 | Prompt(open) | | UNCLEAR | U-14: what triggers the next batch is undefined, and so is how not-yet-asked questions persist. Prompt has no asked/pending marker. |
| G2 | AnswerPrompt(prompt_id, answer) | override from answer | PromptAnswer | | UNCLEAR | U-10: `answer: str` is free text. Mapping it to an override (yes/no/"Sam and Raj") isn't typed, and the people named aren't PersonRefs. |
| G3 | AnswerPrompt | latest PromptAnswer.at | Prompt.answers | | OK | |
| G4 | ConfirmDraft | split shown | Prompts -> dropped | | OK | |
| G5 | ConfirmDraft by non-adder | NotAllowed | BillDraft.added_by | | OK | |
| G6 | EditDraft(assign) | re-split | overrides | summary again | GAP | G-10: there's no op or field for "Raj had none" (remove one person). `assign` needs the full set, which the interpreter doesn't have (draft_summary is text). |
| G7 | n/a | | BillDraft, Prompt in DB | | OK | |
| H1 | EditBill(bill, change, reason) -> P(confirm_action) | re-split from BillLines (adjustments = total - sum(lines)) | W reversing Bill + new Bill(replaces_id, edit_reason); N(bill_changed) | requester; others | GAP | G-10: change is a single-line EditDraft, which can't say "remove Raj from the whole bill". U-3: pending edit in untyped payload. |
| H2 | NotMine(bill) -> P(confirm_action) | re-split | reversing + new Bill; N(bill_changed) | others | OK | Bill found from the last notification (G-9). |
| H3 | DeleteBill(bill="last") | latest Bill added_by speaker, context of chat, not reversal/reversed | W reversing Bill | others | OK | Bills filed from a personal chat (D5) have no conversation_ref, so "in this chat" is ambiguous for them. |
| H4 | EditBill in group | | | group | UNCLEAR | U-8: for an edit requested from a personal chat, posting to the group is the same cross-chat issue. |
| H5 | ShowBillDetails | | BillLine | speaker | OK | Numbered refs: G-9. |
| I1 | ShowBalances() | overall_between per person | all ContextLedgers incl. the single global PersonalContext | speaker | OK | |
| I2 | ShowBalances(with_) | overall_between.breakdown | | speaker | GAP | G-2: breakdown labels need group names. |
| I3 | ShowBalances in group | balances, simplify_debts | | group | OK | |
| I4 | ShowBalances in group | | | group + DM | GAP | G-5. |
| I5 | RecordPayment(payee, amount) -> P(confirm_action) | allocate_payment(named=None) | W Settlement rows (payment_id, recorded_by); N(payment_recorded) | speaker; Sam DM | UNCLEAR | G-4/U-3: Notification has no payment_id or actor field. Only untyped payload. |
| I6 | RecordPayment(context_name) or in group | allocate_payment(named=ctx) | | | GAP | G-2: "for the trip" needs group names. |
| I7 | RecordPayment(payer=Raj) | | Settlement.recorded_by | Raj DM | UNCLEAR | G-4 (same as I5). |
| I8 | NotReceived | latest unreversed payment_id with to_id=speaker | W negating Settlements; N(payment_reversed) | both | OK | |
| I9 | RecordPayment -> P(confirm_action overpayment) | allocate_payment overpay value | | | OK | |
| I10 | UndoPayment | latest payment recorded_by speaker | negating rows; N(payment_reversed) | other | OK | |
| I11 | SquareUp(with_) -> P(confirm_action) | square_up | Settlements(kind=square_up); N(square_up) | both | OK | Group pair amounts are a simplify_debts view, so a settlement doesn't provably make the re-simplified pair 0. Worth a property test. |
| I12 | n/a | balances sums to 0; append-only | | | OK | |
| J1 | Remind(person) | | N(reminder) | Raj DM | GAP | G-4: "at most once per 24h per (sender, Raj)" needs the sender, and Notification has no actor field. |
| J2 | ShowHistory(this_month) | shares by purchased_at in timezone | Bill | speaker (DM if group) | OK | In a group, needs G-5. |
| J3 | ShowHistory(last_n=5) | | Bill | speaker | OK | Follow-up "details 3" needs G-9. |
| J4 | Notifications(on) | | Person.notifications_enabled | | OK | |
| J5 | n/a (tick) | claim_due(now, limit) | Notification.sent_at | | UNCLEAR | U-15: claim_due has no per-person daily cap parameter. It's undefined whether held-flush (D8) and replies count toward the cap, and which day boundary (timezone) applies. |
| K1 | entrypoint | | fakes | | OK | |
| K2 | entrypoint | | | | OK | |
| K3 | entrypoint: /v1/messages, /v1/tick | Orchestrator.handle/tick | | | OK | |
| K4 | entrypoint | | | | OK | |
| K5 | none | | ProcessedMessage(channel, message_id, replies) | stored replies | OK | |
| K6 | none | | unit_of_work(lock_conversation) | | OK | |
| K7 | none | LlmUnavailable | nothing written | speaker | OK | |
| K8 | any money/destructive -> P(confirm_action) | | Prompt | | GAP | G-3: Prompt has no field for who must say "yes". In a group, someone else's "yes" can't be rejected without relying on untyped payload. |
| K9 | n/a | | config | | GAP | G-13: SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY has no entity or counter to enforce it. |

## Gap list (G) and unclear list (U)

- G-1 BillDraft working state (C4, C5, C6, C10, D2, D3): add `lines`, `tax_cents`, `other_adjustments_cents`, `total_cents`, `accepted_difference_cents`, `description`, `purchased_at`, `image_ref`, `image_mime_type`, `owes_all_id` to BillDraft (working copy seeded from Receipt or manual input; replaces `manual_lines`).
- G-2 Group name source (A2, A10, D5, I2, I6): add `conversation_name: str | None` to InboundMessage.
- G-3 Prompt addressee (A4, K8; also A10, A11, D2, C11): add `asked_of: str | None` (person allowed to answer; None = anyone in context) to Prompt.
- G-4 Notification actor/payment (J1, I5, I7; also D6, I8, I10, I11 texts): add `actor_id: str` and `payment_id: str | None` to Notification.
- G-5 Asked-for DM (F14, I4, J2-in-group): add NotificationKind `requested_reply` (exempt from opt-out), with the rendered request in payload.
- G-6 Rule scope lost (F16, C1): resolve_rules returns the winning `Rule`s, or `(RuleInput, RuleScope)` pairs.
- G-7 First-time match (F11, C1): add `match_how: Literal["exact","alias","fuzzy","model"]` + `match_is_new: bool` to LineItem.
- G-8 Phone giver (A12): add `phone_added_by: str | None` to Person.
- G-9 Numbered list reference (D9, H5, J3, D6, H2): add `last_listed_bill_ids: tuple[str, ...]` to Conversation.
- G-10 Remove-person edit (G6, H1): add `except_: tuple[PersonRef, ...]` to EditDraft, and allow `line=None` to mean every line.
- G-12 Item set (F10): add `Item(key)` + `items` store.
- G-13 LLM call counter (K9): add an `LlmUsage(person_id, day, calls)` counter + store.
- U-1..U-15 as described in the table.
