# Design review before building (2026-11-23)

Four independent reviews (use-case coverage, spec consistency, engineering setup,
security/privacy/reliability) of SPEC.md, USE_CASES.md, DECISIONS.md and the repo setup.
~83 raw findings, merged and de-duplicated below. Each item has a recommendation.
Status column: **pending** until the user decides, then **agreed** / **changed** / **rejected**
and the outcome goes into SPEC/USE_CASES/DECISIONS.

## Part 1 — Product decisions (user-visible, need the user)

| # | Problem (example) | Recommendation | Status |
|---|---|---|---|
| P1 | Group bills always include every active member. "Taxi 600, me and Priya" on a trip is impossible; a receipt from before Raj moved out, added after, is wrong. | A group bill may name a subset ("me and Priya", "everyone except Raj"). Default stays all active members. Membership is checked against the purchase date, so recent leavers can still be included. | **changed**: subsets allowed; only current members (no purchase-date check). Leavers' older receipts go via personal splits. |
| P2 | In a busy group chat every message is interpreted (cost) and `Unknown` may get a reply (spam). Casual "ok"/"no" can be taken as answers. Anyone who says "hi" becomes a member (a visiting partner, 10-person trip group). A member who moved out re-joins by posting. | In groups the bot only reacts when addressed: a mention or "split…" prefix, a reply to the bot, a photo, or a clear answer to its open question. Silent on `Unknown`. Membership is explicit: at setup the bot asks people to reply "join" (or someone adds them); a non-member who talks to the bot is asked "join splits here?". Leavers never re-join by posting. | **agreed** |
| P3 | A draft can block a group forever (adder on holiday; later receipts queue behind it). | After the 24h reminder, any active member can cancel or take over the draft. Drafts expire after 3 days with a short group message. | **changed**: any active member can cancel any draft at any time (bot posts who cancelled); drafts auto-expire after 3 days; no take-over. |
| P4 | Payments are one-sided and can't be undone. "Paid Sam 5000" (meant 500) silently creates a 4500 credit; Sam isn't told. Creditors can't record "Raj paid me". | Either party can record a payment. The other party is told and can reply "not received" to reverse it. Paying more than owed asks for confirmation first. "Undo last payment" (reversing entry). A payment said inside a group chat counts for that group. | **agreed** |
| P5 | Personal splits let anyone create debts between other people ("Sam paid, Raj owes all ₹20,000"). A dispute keeps the bill counting. | In personal splits the payer is always the adder. Any participant can reply "not mine": the bill is reversed and the adder is asked to redo it. "Dispute" stays for "the amounts are wrong". | **agreed** |
| P6 | Any participant can edit/delete a bill someone else paid; "delete last bill" is ambiguous; a debtor can wipe their own debt. | Anyone in the bill can propose an edit/delete; only the payer or the adder confirms it (asked if they aren't the requester). "Last bill" means the speaker's last bill in this chat. Group-bill changes are posted in the group. | **changed**: any participant can edit/delete after confirming (no payer/adder approval). |
| P7 | "What do I owe?" or "rules about me" asked in the trip group reveals Flat 4B debts, personal splits and private everywhere rules (diet, religion). | In a group chat, answers only cover that group. Overall balances, cross-group breakdowns, history and everywhere rules are sent to the person's personal chat ("sent you a DM"). | **agreed** |
| P8 | Disputes have no exit: the disputer can't withdraw, the adder can't say "it's correct", nobody is reminded. Batched notifications don't say which bill "dispute" means. | Disputer can withdraw; adder can resolve without editing (disputer told); open disputes show in balances. Bills in a batched message are numbered ("dispute 2"). | **changed**: no disputes at all. Any participant edits the bill directly, with an optional reason; everyone in the bill is notified of the change and the reason. "Not mine" is an edit: you are removed, your items are re-split among the rest; the bot shows the effect and asks you to confirm, then everyone is told. |
| P9 | Unanswered questions block saving; two people answering differently loops forever. | The adder can confirm with questions still open (the split shown is used). On a second conflict, the adder's answer wins. | **changed**: adder can confirm anytime; on conflicting answers the latest answer wins, no re-asking. |
| P10 | Membership can be changed against people ("Raj moved out" by anyone; adding a stranger who then owes on every bill). | Membership changes are announced in the group. "X moved out" about someone else needs a second member's or X's confirmation. | **changed**: membership changes take effect immediately and are announced in the group; no confirmation. |
| P11 | No opt-out; "remind Raj" can be spammed; reports can get the bot number banned. | "stop"/"start" per person silences notifications and reminders. "Remind" at most once per 24h per pair. Daily per-person notification cap. | **agreed** |
| P12 | Same receipt added twice (you and Sam both upload Toit; or both of you add the same dinner as a personal split). | Warn on a likely duplicate (same group or same pair, same total, within 3 days) before confirming. | **agreed** |
| P13 | You owe Sam 800 on the trip, Sam owes you 800 in Flat 4B: overall even, but both group balances stay non-zero forever. | "Square up with Sam" writes matching offsetting settlements in each context so they all clear. | **agreed** |
| P14 | Rent 30000 split 12000/9000/9000; "Sam's part was ₹100" on a ₹250 line is ambiguous (weights rescale). | Manual bills may give exact amounts per person (must add up to the total, else the bot asks). An amount override on a line must add up to the line, or the remainder is split equally among the others. | **agreed** |
| P15 | No way to fix parser mistakes during review (₹120 read as ₹720, missing line, junk "bag 0.50"); fixing the total doesn't say what absorbs the difference. | Review supports "line 4 is 120", "remove the bag", "add water 40", "total is 1840". If lines + tax + adjustments still don't match the total, the bot shows the difference and the adder either fixes a line or accepts it as an adjustment. | **agreed** |
| P16 | A 45-line receipt makes a wall of text. | The summary shows per-person totals, who was skipped and flagged lines. "details" shows the numbered full list; lines can be referred to by number or name. | **agreed** |
| P17 | A wrong item match ("OAT MLK" → milk) is permanent and affects every group. | First-time matches are shown in the summary ("OAT MLK → milk?"); "that's not milk" fixes the mapping. | **changed**: matches (raw name → item key) are remembered per group, and per adder for personal splits, so a wrong match only affects that place. Item keys themselves stay install-wide, so rules about "milk" still apply everywhere. |
| P18 | Typo in someone's number, or someone added to a group by mistake, can't be fixed. | A person's number can be corrected while they've never used the bot. "Remove X, added by mistake" ends the membership (only if they have no bills there; otherwise use edits). | **changed**: groups need nothing extra (people removed from the group chat stop being members; wrong people on a bill are fixed by editing). In personal chats the adder can correct a number they gave for someone (only while that person has never used the bot, so nobody can hijack a real user). |
| P19 | There's no "include" rule, so "Raj drinks milk now" can only delete a rule, and a group can't override Raj's everywhere exclude. | Keep three rule kinds. "Raj drinks milk now" deletes the rule in that scope. Accept that a group can't force-include someone's everywhere exclude (they can still answer per bill). | **agreed** |
| P20 | A coupon "MILK 20% OFF" is split among everyone, so Raj (who skips milk) gets a credit. | The receipt reader links a discount line to the item it reduces; it gets that item's key, so the same people share it. Unclear discounts are shared by all. | **agreed** |
| P21 | History and membership use the date a bill was added, not when the purchase happened; "this month" has no timezone. | Use the purchase date (from the receipt, or "yesterday" in a manual bill), else the date added. "What did I spend" = my shares. Timezone in config. | **agreed** |
| P22 | Someone wants to be removed from the system. | Specify now, build later: "forget me" removes identities, nicknames, rules and images, and replaces name/phone with "Former member" while keeping ledger rows so others' balances stay correct. | **agreed** |
| P23 | Adding 5 bills with someone who hasn't used the bot gives 5 invite texts. | Invite text only on the first bill with each non-user. | **agreed** |
| P24 | Tip rule jumps: a: +1000, b: −1000 → raw sum 0 → equal 50/50; change b to −999 → a pays all 100. | Drop the "raw sum ≤ 0" condition: weight by clamped totals; split equally only if all clamped totals are 0. (Changes a rule you approved.) | **agreed** |

## Part 2 — Spec fixes (technical; recommendation applied unless the user objects)

| # | Problem | Fix |
|---|---|---|
| S1 | Two balance models contradict: pairwise debts vs group balance + `simplify_debts`. Following the bot's own "pay Raj" advice corrupts the overall view. | Group balance (per member, incl. settlements) is the source of truth inside a group. "Who owes whom" in a group = `simplify_debts` output. Overall with Sam = sum over groups of the simplified pairs + personal-split pairs. A settlement in a group always books to that group. |
| S2 | Group balance formula ignores settlements. | paid − owed + settlements sent − settlements received, per context. |
| S3 | Bills store only shares, so "details" and edits can't be rebuilt. | Add `BillLine` (bill, name, amount, item key, assignees with weights). |
| S4 | Answering one soft question replaces the item's whole assignment and silently drops other open questions on it. | An answer adjusts the current assignment; other questions on that item stay open. |
| S5 | Learning ("same way twice") isn't defined; no answer history survives a dropped draft. | Per subject: excluded twice → `exclude`; sole assignee twice → `only`; anything else teaches nothing. New `AnswerObservation` entity. |
| S6 | Draft states and transitions are never listed. | Add a state table: queued, awaiting_people, reviewing, awaiting_confirm, saved, cancelled, expired; plus prompts below. Define queued-draft start after save/cancel, late answers, parse failures. |
| S7 | Only engine questions are persisted; "who's this with", "which Sam", "confirm total", "dispute reason", "confirm delete" aren't, so restart-resume breaks. | Generalise `PendingQuestion` into `Prompt` with a `kind` and payload. |
| S8 | Participants snapshot vs recompute is undefined; leaving/joining mid-draft undefined. | Snapshot at draft creation; a leaver's open questions are dropped; the adder leaving cancels the draft. |
| S9 | Conflict detection after an answer is applied isn't defined. | Questions stay open for conflicts until confirm; a person's later answer replaces their earlier one. |
| S10 | Manual bills don't fit `split_receipt`. | A manual bill is one synthetic line item. |
| S11 | "Add to Flat 4B" from a personal chat: group may already have a draft; rules/questions re-resolve. | Re-resolve with group rules, ask in the personal chat, adder confirms there; doesn't touch the group's own draft. |
| S12 | Notifications quote balance "with the adder" (wrong when someone else paid); text frozen when queued; non-users' messages not held. | Balance with the payer; text rendered when sent; held for non-users until their first message; `bill_ids` on notifications. |
| S13 | Settlements can't be reversed. | `reverses_id` on settlements; undo command. |
| S14 | `fold_item_tax` blows up with negative taxed lines (1000 and −999 → +100000/−99900); its input type is undefined. | Weight by taxed lines clamped at 0; if 0, tax stays as an adjustment. Input type `TaxedLine(item, taxed)`. |
| S15 | `simplify_debts` is called "minimal"; greedy isn't (+6,+4,−4,−3,−3: greedy 4 transfers, optimal 3). | Call it "greedy, few transfers". |
| S16 | Settle-up tie-break "oldest unsettled bill" undefined. | Oldest bill in that context between the pair. |
| S17 | Member with both `exclude` and `soft_exclude` for one item. | `exclude` wins, no question. Learned can replace learned. |
| S18 | Where canonicalize lives; `CommandInterpreter.canonicalize` missing from §8. | Service using a pure matcher + the port; list it in §8. |
| S19 | Milestone order: M1 needs the taxed flag; M3 needs answer history (M2); M7 "notify" needs M8's outbox; config only in M9; AddMember in two milestones. | Define the tax input type in engine (M1); `AnswerObservation` in M2; M7 doesn't notify; `config.py` from M2; AddMember in M7. |
| S20 | E.164 needs country rules ("098765 43210"). | Use the `phonenumbers` library (pure, allowed in domain). |

## Part 3 — Security & reliability additions to the spec

| # | Problem | Fix |
|---|---|---|
| R1 | Anyone who can reach the API can act as anyone. | Shared secret `SMARTSPLIT_API_TOKEN` (Bearer) on every `/v1/*` route; `/healthz` open. "Out of scope: auth" becomes "multi-tenant auth". |
| R2 | Retried webhook deliveries double-apply ("paid 500" twice). | Required `message_id` on `InboundMessage`; store it with the reply in the same transaction; a repeat returns the stored reply. |
| R3 | Concurrent messages in one chat can lose answers or save twice; no transaction boundary. | One transaction per inbound message, serialized per conversation (advisory lock); Repository port gets a unit of work; LLM calls happen before the lock. |
| R4 | `tick` running twice sends duplicates; lost response loses messages. | Claim rows with `FOR UPDATE SKIP LOCKED`; at-most-once delivery (logged in DECISIONS). |
| R5 | Prompt injection via profile names, receipt text or chat can make the model emit SettleUp/DeleteBill. | Model output is only a proposal; services do all permission checks. Money-moving or destructive commands always get a plain restatement + "yes". Untrusted text passed as data. People resolved only from the speaker's nameable list. |
| R6 | Model output not validated (invented lines, quantity 0, negative manual bills). | Validate into domain types; amounts positive with a configurable maximum. |
| R7 | LLM outage mid-flow. | Timeout from config; on failure reply "couldn't read that, try again" and leave state unchanged. |
| R8 | WhatsApp sometimes gives only a hidden id (LID) with no phone, but phone is required. | Optional `sender_phone` on `InboundMessage`; unknown LID without phone → the bot asks them to message it 1:1 first. |
| R9 | Logs/images/secrets policy missing; Postgres in docker-compose exposed on all interfaces with default password. | No message bodies, images, prompts or full phone numbers in logs; mask numbers in bot text; secrets as `SecretStr`; max body/image size; image storage + pruning defined; compose binds `127.0.0.1`. |
| R10 | Cost blow-up (50 photos). | Cap queued drafts (3), parse queued receipts only when they start, per-person daily LLM-call cap, `max_tokens` in config. |
| R11 | Adding by number reveals the stored name ("Added Priya Sharma"). | Show the adder only the name they gave. |
| R12 | Forced `tool_choice` may not be supported on the configured model. | Verify against current API docs in M5/M6 before relying on it. |

## Part 4 — Engineering setup

| # | Problem | Fix | When |
|---|---|---|---|
| E1 | No CI: "check.sh passes" is only self-reported; db tests never run independently. | GitHub Actions with a Postgres service running `scripts/check.sh` on every push/PR, plus a job that fails if `tests/acceptance/**` or `scripts/check.sh` differ from `main`. | before M1 (**needs user OK**) |
| E2 | Frozen files are only protected against Edit/Write; shell commands (`cat >`, `sed -i`, `uv run python`) can change them. | E1's CI check is the real guard. | before M1 |
| E3 | Purity isn't enforced: core can call `datetime.now`, `uuid4`, `random`, `logging`, `os.environ`. | Ruff banned-api (TID251) + DTZ for domain/engine/ledger. | before M1 |
| E4 | Import contracts miss: sqlalchemy only in adapters/db; fastapi/typer only in their entrypoint; adapters independent; config only at the edges. | Add those import-linter contracts. | before M1 |
| E5 | `db` marker says DATABASE_URL (the dev DB) while CLAUDE.md says TEST_DATABASE_URL. | Fix marker text; fixture refuses DBs not ending in `_test`. | before M1 |
| E6 | No hypothesis profiles; flaky deadlines on slow runners invite "fixing" tests. | `tests/conftest.py` with `ci` (no deadline, derandomized) and `dev` profiles. | before M1 |
| E7 | `tests/` aren't type-checked. | mypy `files = ["src", "tests"]`. | before M1 |
| E8 | Review gate doesn't look for gate-gaming (`noqa`, `type: ignore`, `pragma: no cover`, skip/xfail, config loosening); diff range is guesswork. | REVIEW.md step 0; git tag per milestone (`m0-done`, `m1-done`, …). | before M1 |
| E9 | No reminder to re-read docs after context compaction. | SessionStart `compact` matcher in `.claude/settings.json`. | before M1 (**needs user OK**) |
| E10 | Small: no `.python-version` (runs on 3.13, targets 3.12); no ruff FIX/TD rule for TODOs; unnecessary rapidfuzz mypy ignore; session_start prints "ready" even if Postgres failed; one aggregate coverage number. | Fix each; stricter coverage for engine/ledger in CI. | before M1 |
| E11 | `.env.example` lacks the §12 settings; no `config.py`; no network block in tests; live-test gate unimplemented. | `.env.example` now; `config.py` in M2; `pytest-socket` + live gate in M5. | M2 / M5 |
| E12 | Test DB fixture (fail, not skip; schema per test) and Alembic not set up. | In M2, with a test that migrations match the models. | M2 |
| E13 | Working branch not named in CLAUDE.md; `main` unprotected. | Name the branch in CLAUDE.md (**needs user OK**); branch protection on GitHub (user action). | before M1 |
| E14 | PROGRESS "Next up" and DECISIONS "Open" are stale; DECISIONS currency line refers to per-group currency. | Clean up after this review. | now |
