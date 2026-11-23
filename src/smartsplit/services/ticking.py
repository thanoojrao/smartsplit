"""What happens with nobody talking: delivering the outbox, nudging and expiring idle drafts,
and retrying receipts left unread (SPEC 10.4, 10.8; CONTRACTS section 5).

Each step uses its own transactions. Delivery takes no conversation lock (the claim has its
own), so it never waits behind a chat; a draft is changed only under its chat's lock and only
if nothing happened to it meanwhile.
"""

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import Notification
from smartsplit.ports.errors import StaleDraftError
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.lifecycle import finish, start_next
from smartsplit.services.notifications import remember_listed, render
from smartsplit.services.receipt_reading import ReceiptReader
from smartsplit.services.turn import OrchestratorSettings, Turn

STUCK_AFTER = timedelta(minutes=2)
"""A receipt still unread this long after its last activity is read again: long enough that a
read in progress isn't doubled, short enough that a model outage passes quickly."""


@dataclass(frozen=True, slots=True)
class Ticker:
    repository: Repository
    reader: ReceiptReader
    clock: Clock
    ids: IdGenerator
    settings: OrchestratorSettings

    def tick(self) -> list[OutboundMessage]:
        now = self.clock.now()
        replies = self.deliver(now)
        replies += self.idle_drafts(now)
        with self.repository.unit_of_work() as uow:
            stuck = [d.id for d in uow.drafts.parsing_idle_since(now - STUCK_AFTER)]
        return replies + self.reader.read_all(None, stuck)

    def deliver(self, now: datetime) -> list[OutboundMessage]:
        """Claim what may be sent, one message per person, rendered with today's balances."""
        zone = ZoneInfo(self.settings.timezone)
        day_start = datetime.combine(now.astimezone(zone).date(), time(), zone)
        out: list[OutboundMessage] = []
        with self.repository.unit_of_work() as uow:
            claimed = uow.notifications.claim_due(
                now,
                self.settings.notifications_per_tick,
                self.settings.max_notifications_per_day,
                day_start,
            )
            batches: dict[str, list[Notification]] = {}
            for notification in claimed:
                batches.setdefault(notification.recipient_id, []).append(notification)
            for recipient, batch in batches.items():
                chat = uow.conversations.personal_for(recipient)
                if chat is None:
                    continue
                text, listed = render(uow, recipient, batch, self.settings.currency)
                remember_listed(uow, chat, listed)
                out.append(OutboundMessage(chat.key, recipient, text))
        return out

    def idle_drafts(self, now: datetime) -> list[OutboundMessage]:
        """One reminder after a day without activity; expired after three (SPEC 10.4)."""
        with self.repository.unit_of_work() as uow:
            due = uow.drafts.due_for_reminder_or_expiry(now - self.settings.draft_reminder_after)
        out: list[OutboundMessage] = []
        to_parse: list[str] = []
        for draft in due:
            try:
                replies, more = self._idle(draft, now)
            except StaleDraftError:
                continue  # someone answered meanwhile
            out += replies
            to_parse += more
        return out + self.reader.read_all(None, to_parse)

    def _idle(self, seen: BillDraft, now: datetime) -> tuple[list[OutboundMessage], list[str]]:
        with self.repository.unit_of_work(lock=seen.conversation) as uow:
            draft = uow.drafts.get(seen.id)
            chat = uow.conversations.get(seen.conversation)
            adder = uow.people.get(seen.added_by)
            if draft != seen or chat is None or adder is None:
                return [], []
            turn = Turn(uow, self.ids, now, self.settings, adder, chat)
            if now - draft.last_activity_at >= self.settings.draft_expires_after:
                finish(turn, draft, DraftState.EXPIRED)
                turn.reply(f"The {draft.description} bill expired. Nothing was saved.")
                start_next(turn, draft)
            elif draft.reminded_at is None or draft.reminded_at < draft.last_activity_at:
                uow.drafts.update(replace(draft, reminded_at=now), expected_state=draft.state)
                who = uow.people.get(draft.added_by)
                name = who.display_name if who else "whoever added it"
                turn.reply(
                    f'Still waiting on the {draft.description} bill. {name}, say "yes" to save '
                    'it, or "cancel".'
                )
            return turn.replies, turn.to_parse
