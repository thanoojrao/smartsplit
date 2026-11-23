# SmartSplit — Use cases (DRAFT, under review with the user)

Real-life situations in a shared house, checked against the design in SPEC.md.

Status: ✅ covered · 🟡 partly covered / unspecified · ❌ not covered · ⛔ out of scope by decision

## A. Group setup

| # | Use case | Status | Where / gap |
|---|---|---|---|
| A1 | Create a house group with a currency and add members | ✅ | §4 Group, §11 CLI |
| A2 | Refer to members by nickname ("Raj", "rajesh") | ✅ | Person.aliases |
| A3 | Person in several groups (house + trip) | ✅ | Group member ids |
| A4 | Someone moves out: stop including them, keep their balance until settled | ❌ | No remove/deactivate member; old rules and open balance undefined |
| A5 | Someone moves in mid-month | 🟡 | Adding works; nothing stops older bills from including them |

## B. Adding bills

| # | Use case | Status | Where / gap |
|---|---|---|---|
| B1 | Snap a grocery receipt; sender paid | ✅ | §7, §10 |
| B2 | Someone else paid ("Sam paid for this") | 🟡 | CLI has `--payer`; no chat way to set payer |
| B3 | Bill without a receipt ("paid 1200 electricity, split all") | ✅ | AddManualExpense |
| B4 | Misread receipt / total doesn't add up | ✅ | §7 warnings → confirm total |
| B5 | Fix a misread line (wrong price, missing item) | 🟡 | EditSplit exists; editing line items not specified |
| B6 | Same receipt uploaded twice | ❌ | No duplicate detection |
| B7 | Two people photograph different bills at the same time | 🟡 | Orchestrator states one flow; concurrency per group unspecified |
| B8 | Cancel a bill halfway through | 🟡 | No cancel command |
| B9 | Paid by two people (split card payment) | ⛔ | Not planned; could be two manual expenses |
| B10 | Foreign currency receipt | ⛔ | One currency per group |
| B11 | Recurring bills (rent, wifi) | ⛔ | Not planned; manual expense each month |

## C. Splitting a receipt

| # | Use case | Status | Where / gap |
|---|---|---|---|
| C1 | Shared items split equally among everyone | ✅ | §5 |
| C2 | "Raj doesn't drink milk" applied automatically | ✅ | §5 exclude rules |
| C3 | "Protein powder is only Sam's" | ✅ | §5 only rules |
| C4 | "Sam usually doesn't eat chips" → include but ask | ✅ | §5 soft_exclude |
| C5 | Messy receipt names match rules ("2% MLK GAL" → milk) | ✅ | §6 canonicalize |
| C6 | Coupon / discount lines | ✅ | §5 negative items |
| C7 | Tax, tip, service charge | ✅ | §5 proportional adjustments |
| C8 | Some items taxed, some not (US "T", India GST slabs) | ❌ | Proposed: per-item tax in M5/M7 (pending decision) |
| C9 | Quantity lines: "3 x yogurt", 2 for Sam, 1 for Raj | ❌ | Engine only does equal splits per line |
| C10 | Unequal share of one item ("I use 2/3 of the rice") | ❌ | Same: no weights in the frozen engine contract |
| C11 | Item for a guest / non-member | ❌ | Only members can be assigned |
| C12 | Payer's personal items in a shared shop ("the shampoo is mine") | ✅ | Override via answer/EditSplit |

## D. Preferences (rules)

| # | Use case | Status | Where / gap |
|---|---|---|---|
| D1 | State, list, delete rules in chat | ✅ | §6, §8 |
| D2 | Bot learns from repeated answers | ✅ | §6 learning |
| D3 | Preference changes ("Raj drinks milk now") | ✅ | New stated rule replaces old |
| D4 | Category rules ("Raj doesn't drink alcohol" → beer, wine, vodka) | ❌ | Rules are per item key only |
| D5 | Temporary absence ("Raj is away this week, leave him out") | ❌ | No member-wide or time-bound rules |

## E. Questions and confirmation

| # | Use case | Status | Where / gap |
|---|---|---|---|
| E1 | Bot asks when unsure, answers in chat | ✅ | §10 |
| E2 | Review the split and confirm/edit before saving | ✅ | §10 |
| E3 | Who may answer/confirm? Two people answer differently | 🟡 | Unspecified (anyone? payer only? last answer wins?) |
| E4 | Nobody answers for days | 🟡 | No timeout / default behaviour |

## F. Money and settling

| # | Use case | Status | Where / gap |
|---|---|---|---|
| F1 | "Who owes what?" | ✅ | §9 balances |
| F2 | Fewest payments to settle everyone | ✅ | §9 simplify_debts |
| F3 | Record a payment, full or partial | ✅ | §9 Settlement |
| F4 | Undo a wrong expense | 🟡 | Ledger supports reversing entries; no chat command for it |
| F5 | History ("what did I pay for this month?") | ❌ | No history/statement command |
| F6 | Payment links (UPI/Venmo) | ⛔ | §12 future |
