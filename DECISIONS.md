# Decisions

One line per decision: what was decided, and why. Newest at the bottom of each section.

## Made by the user (do not revisit without asking)

- Own ledger is the source of truth. A Splitwise sync may come later as an optional adapter. Why: self-hostable, no external dependency.
- WhatsApp via Baileys (unofficial) later, as a separate Node gateway calling `POST /v1/messages`, on a dedicated bot number. Not part of this build.
- Stack: Python 3.12+, FastAPI, SQLAlchemy 2 + Alembic, Postgres, uv. Why: user's preference.
- First build = the core engine with no WhatsApp (SPEC §1).
- Open source, self-hosted by others.

## Made by Claude during the build

- (M0) Money as integer cents, with exact Fractions inside the split engine, and largest-remainder rounding with ties broken by member order. Why: deterministic and always sums exactly to the receipt total.
- (M0) Layering enforced by import-linter in `scripts/check.sh`. Why: stops long autonomous runs from eroding the architecture.

## Open (waiting for the user)

(none)
