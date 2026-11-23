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
- (Vision review) Personal-chat splits: people added are notified and the bill counts immediately; they can reply ok / details / dispute (disputed bills are flagged until the adder fixes them). People who never used the bot are not cold-messaged; the adder gets a forwardable wa.me invite, and the newcomer sees pending splits on first contact. Repeated bills to the same person are batched into one message. Why: Splitwise-like, nothing stuck in limbo, avoids WhatsApp ban risk.
- (Vision review) Picking people in a personal chat: caption ("split with Sam and Raj"), else the bot offers a numbered list of recent/frequent people and groups; unknown names → share a contact card or number; ambiguous names → bot asks. Shortcuts: "Sam paid", "Sam owes all of it", "add to <group>". Why: one-message happy path, no menus.
- (Vision review) Settling up against an overall balance is allocated across the groups automatically, largest debt first (oldest on ties); the user can still target one group. Why: every group's balance stays correct.

## Made by Claude during the build

- (M0) Money as integer cents, with exact Fractions inside the split engine, and largest-remainder rounding with ties broken by member order. Why: deterministic and always sums exactly to the receipt total.
- (M0) Layering enforced by import-linter in `scripts/check.sh`. Why: stops long autonomous runs from eroding the architecture.

## Open (waiting for the user)

Vision review in progress; M1 paused until the use-case list (docs/USE_CASES.md, to be rewritten) is agreed.

- Personal-chat splits as bills with no group (changes "every bill belongs to a group" in the domain model) (recommended, follows from overall balances).
- Do preference rules apply per group or everywhere that person is?
- Item-level weights/quantities in the split engine (changes the frozen §5 contract) (recommended).
