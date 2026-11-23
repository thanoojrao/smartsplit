# SmartSplit — Use cases

Every user-facing situation the first build must handle, with the expected behaviour,
where the spec covers it, and the milestone that delivers it. If a situation isn't here,
it isn't in scope; the last section lists what is deliberately left out.

Examples use ₹ and these people: **you** (Thanoo), **Sam**, **Raj**, **Priya**.
Groups: **Flat 4B** (you, Sam, Raj) and **Goa trip** (you, Raj, Priya).

## A. Getting started and people

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| A1 | You message the bot for the first time in a personal chat | You're created from your chat identity (name from your profile); short welcome + help | §6.1, §10.2 | M7 |
| A2 | The bot is added to the Flat 4B group chat; first message arrives | Group is created and linked to the chat; the sender becomes a member | §10.2 | M7 |
| A3 | Someone who hasn't spoken yet writes in Flat 4B | They become a member from now on | §10.2 | M7 |
| A4 | "add Priya" with her contact card or number, in a group | Priya is created (if new) and becomes a member from now on | §6.1, §10.5 | M7 |
| A5 | Same person reached two ways (WhatsApp number and hidden id) | Both chat identities map to one person | §4.1 | M2 |
| A6 | Numbers typed in different formats ("098765 43210", "+91 98765-43210") | Normalized to E.164 and recognised as the same person | §3, §6.1 | M2 |
| A7 | You call him "Sam", Raj calls him "Samuel" | Each nickname works for its owner only | §4.1, §6.1 | M7 |
| A8 | "split with Sam" when you know two Sams | Bot asks "Sam from Flat 4B, or Sam K?" | §6.1 | M7 |
| A9 | "split with Meera" and the bot doesn't know her | Bot asks for her contact card or number; no name-only people | §6.1 | M7 |

## B. Groups and membership

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| B1 | "Raj moved out" | Membership ends; Raj isn't in new bills; his balance stays until settled and he can still see it | §10.5 | M8 |
| B2 | Raj moved out | Flat 4B's rules about Raj stop applying; his own everywhere rules are untouched | §6.2 | M8 |
| B3 | Priya moves in mid-month | She's in bills from now on, never in older ones | §4.2, §10.5 | M8 |
| B4 | Raj moves back in later | New membership; Flat 4B's old rules about him apply again | §4.2, §6.2 | M8 |
| B5 | Raj is in Flat 4B and the Goa trip | Separate bills and balances per group; one overall total | §4.2, §9 | M4 |

## C. Adding a bill in a group

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| C1 | You send a receipt photo in Flat 4B | Parsed, split among active members using rules, summary shown, waits for confirm | §10.3 | M7 |
| C2 | "Sam paid" with the photo | Payer is Sam instead of the sender | §8 | M7 |
| C3 | Bill with no receipt: "electricity 1800, split all" | Manual bill, split equally among active members | §8, §10.3 | M7 |
| C4 | Receipt total doesn't match its lines | Summary warns; you confirm or fix the total before saving | §7 | M7 |
| C5 | A line is hard to read | Summary flags "couldn't read line 4 clearly: SPRT DRNK ₹120?"; must be confirmed or fixed | §7 | M7 |
| C6 | Second receipt while the first is still under review | "I'll do this one after we finish the Toit bill"; queued, handled next | §10.3 | M7 |
| C7 | "cancel" during review | Draft dropped, nothing saved | §10.3 | M7 |
| C8 | Nobody finishes a draft for 24 hours | The adder gets one reminder; still nothing saved | §10.3, §10.6 | M8 |
| C9 | Receipt in a different currency | Warning; nothing converted | §7 | M5 |
| C10 | Group bill saved | Summary and new balances posted in the group chat; no personal messages | §10.4 | M8 |

## D. Personal splits (1:1 chat with the bot)

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| D1 | Photo with caption "split with Sam and Raj" | Personal split between you, Sam and Raj; summary; confirm | §10.3 | M7 |
| D2 | Photo with no caption | Bot asks "Who's this with?" with a numbered list of recent/frequent people and groups | §10.3 | M7 |
| D3 | "Sam owes me all of it" | Sam's share is the full amount | §8 | M7 |
| D4 | "add to Flat 4B" from your personal chat | Becomes a Flat 4B group bill; summary posted in the group | §8, §10.3 | M7 |
| D5 | Personal split saved; Sam has used the bot | Sam gets a personal message: bill, his share, his new overall balance with you; replies ok / details / dispute | §10.4 | M8 |
| D6 | Personal split saved; Priya has never used the bot | Priya isn't messaged; you get a forwardable invite text | §10.4 | M8 |
| D7 | Priya sends her first message | She sees what's waiting for her ("Thanoo added 2 splits, you owe ₹400…") | §10.4 | M8 |
| D8 | You add 3 bills with Sam in a few minutes | Sam gets one combined message | §10.4, §10.6 | M8 |

## E. How a receipt is split

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| E1 | Shared item, 3 people, ₹10.00 | 334 / 333 / 333 cents; extra cent by member order | §5 | M1 |
| E2 | Raj never drinks milk (exclude) | Milk split among the others; Raj still shares the rest | §5 | M1 |
| E3 | Protein powder is only Sam's (only) | Sam pays all of it | §5 | M1 |
| E4 | Oat milk is only Sam's and Raj's | Split between the two | §5 | M1 |
| E5 | Sam usually skips chips (soft exclude) | Sam stays in, bot asks about it | §5 | M1 |
| E6 | Everyone is excluded from an item | Split among everyone; bot asks who it's for | §5 | M1 |
| E7 | "2 yogurts for Sam, 1 for Raj" / "70/30" / "Sam's part was ₹100" | Weighted split | §5 | M1 |
| E8 | Coupon line (negative) | Reduces the shares of the people it's assigned to | §5 | M1 |
| E9 | Tax, tip, service charge | Spread in proportion to each person's items | §5 | M1 |
| E10 | Some lines marked taxed, some not | Tax only on the taxed lines (and so only on the people who had them) | §5.1 | M1 |
| E11 | Receipt doesn't mark taxed lines | Tax spread like other adjustments | §5.1 | M1 |
| E12 | A discount assigned to one person, plus tip | Nobody gets "paid" by the tip; tip weighted by positive item totals | §5 | M1 |
| E13 | Messy names ("2% MLK GAL") | Matched to "milk" (exact, then fuzzy, then the model); remembered | §6.4 | M3 |
| E14 | Any receipt | Shares always add up exactly to the total; every participant listed | §5 | M1 |

## F. Preferences (rules)

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| F1 | Raj, in his personal chat: "I don't drink milk" | Everywhere rule for Raj | §6.2 | M3 |
| F2 | Raj says the same in Flat 4B | Flat 4B rule only | §6.2 | M3 |
| F3 | Anyone in Flat 4B: "protein powder is Sam's" | Flat 4B rule | §6.2 | M3 |
| F4 | You, in your personal chat: "Sam never shares dessert" | Your note; used only in personal splits you add | §6.2 | M3 |
| F5 | Same answer twice in Flat 4B ("not Sam" for chips) | Learned Flat 4B rule; stops asking | §6.5 | M3 |
| F6 | Same answer twice in your personal splits | Learned rule in your notes | §6.5 | M3 |
| F7 | Group rule and Raj's everywhere rule disagree | Group rule wins in that group; stated beats learned; newest wins | §6.3 | M3 |
| F8 | Sam adds a personal split with you | Your notes about Sam don't apply (Sam's bill uses Sam's notes) | §6.3 | M3 |
| F9 | "Raj drinks milk now" | Replaces the existing rule in that scope | §6.2 | M3 |
| F10 | "what rules are about me?" | Every rule about you, with scope and who set it | §6.2 | M7 |
| F11 | Deleting rules | Everywhere: only the subject. Group: any active member (subject told). Notes: only the owner | §6.2 | M7 |
| F12 | Summary in the Goa trip skips Raj via his everywhere rule | Shows "Raj skipped: milkshake" without the reason | §10.3 | M7 |

## G. Questions and confirmation

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| G1 | Up to 3 questions | Asked together in one message | §10.3 | M7 |
| G2 | More than 3 questions | Asked in batches | §10.3 | M7 |
| G3 | Anyone in the group answers | Answer is applied and the split recalculated | §10.3 | M7 |
| G4 | Two people answer differently | Bot asks again, showing both answers | §10.3 | M7 |
| G5 | Someone other than the adder says "yes" | Not saved; only the adder confirms | §10.3 | M7 |
| G6 | "edit: Raj had none of the wine" before confirming | Split recalculated, summary shown again | §8, §10.3 | M7 |
| G7 | Server restarts mid-review | Review resumes where it was | §10 | M7 |

## H. After saving

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| H1 | Sam replies "dispute" | Bot asks what's wrong, tells you, flags the bill; it still counts | §10.4 | M8 |
| H2 | You fix a disputed bill | Edit resolves the dispute; everyone told their new share | §10.4 | M8 |
| H3 | "edit the Toit bill: Raj wasn't there" | Bot shows the change, asks to confirm; stored as reversal + new bill; participants told | §10.4 | M8 |
| H4 | "delete last bill" | Confirm, then stored as a reversing bill; participants told | §10.4 | M8 |
| H5 | "details" on a bill | Line-by-line breakdown of that bill | §8 | M8 |

## I. Balances and settling up

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| I1 | "what do I owe?" | Overall total per person | §9 | M4 |
| I2 | "what do I owe Sam?" | Total with Sam plus breakdown: Flat 4B, Goa trip, personal splits | §9 | M4 |
| I3 | "balances" in Flat 4B | Group balances and the fewest payments to settle the group | §9 | M4 |
| I4 | "paid Sam 500" | Spread across contexts where you owe Sam, largest debt first | §9 | M8 |
| I5 | "paid Sam 500 for the trip" | Recorded against the Goa trip only | §9 | M8 |
| I6 | You pay Sam more than you owe | The extra is recorded in personal splits (Sam now owes you) | §9 | M4 |
| I7 | Any time | Every group's balances sum to 0; bills and payments are never edited, only reversed | §9 | M4 |

## J. Reminders and history

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| J1 | "remind Raj" | Raj gets a friendly nudge with his balance (if he has used the bot) | §10.5 | M8 |
| J2 | "what did I spend this month?" | Short total and list | §10.5 | M8 |
| J3 | "show last 5 bills" | Short list | §10.5 | M8 |

## K. Running it (self-hosters and developers)

| # | Situation | Expected behaviour | Spec | M |
|---|---|---|---|---|
| K1 | Try the full flow with no API key | CLI with fake adapters | §11 | M9 |
| K2 | Try it with real Claude | CLI `--live` with `ANTHROPIC_API_KEY` | §11 | M9 |
| K3 | Connect a chat gateway later | `POST /v1/messages` and `POST /v1/tick` | §11 | M9 |
| K4 | Configure the install | Currency, country code, model, thresholds, invite text via env | §12 | M9 |

## Not in this build

Payment links (UPI/Venmo), automatic reminders and weekly summaries, item categories
("no alcohol"), currency conversion, one bill paid by two people, recurring bills, the WhatsApp
gateway, Splitwise sync, a web UI, accounts/multi-tenant hosting, and asking someone to confirm a
learned rule as their own everywhere rule. See SPEC §13.
