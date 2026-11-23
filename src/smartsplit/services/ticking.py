"""What happens with nobody talking: delivering the outbox, nudging and expiring idle drafts,
and pruning old chat (SPEC 8.6, 10.4, 10.8; CONTRACTS section 5).

Each step uses its own transactions. Delivery takes no conversation lock (the claim has its
own), so it never waits behind a chat; a draft is changed only under its chat's lock and only
if nothing happened to it meanwhile. Everything sent is stored in its chat's transcript.
"""

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import ChatRef, Notification
from smartsplit.ports.errors import StaleDraftError
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.lifecycle import finish, start_next
from smartsplit.services.notifications import render
from smartsplit.services.sending import send
from smartsplit.services.turn import OrchestratorSettings, Said, Turn


@dataclass(frozen=True, slots=True)
class Ticker:
    """Everything `Orchestrator.tick` does, in order: deliver, nudge or expire, prune."""

    repository: Repository
    clock: Clock
    ids: IdGenerator
    settings: OrchestratorSettings

    def tick(self) -> list[OutboundMessage]:
        """Messages for any chat; safe to run often, and from more than one process."""
        now = self.clock.now()
        replies = self.deliver(now)
        replies += self.idle_drafts(now)
        with self.repository.unit_of_work() as uow:
            uow.chat.delete_older_than(now - timedelta(days=self.settings.chat_history_days))
        return replies

    def deliver(self, now: datetime) -> list[OutboundMessage]:
        """Claim what may be sent, one message per person, rendered with today's balances."""
        zone = ZoneInfo(self.settings.timezone)
        day_start = datetime.combine(now.astimezone(zone).date(), time(), zone)
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
            said: list[Said] = []
            for recipient, batch in batches.items():
                chat = uow.conversations.personal_for(recipient)
                if chat is None:
                    continue
                text, bill_ids = render(uow, recipient, batch, self.settings.currency)
                refs = tuple(ChatRef("bill", b) for b in bill_ids)
                payments = dict.fromkeys(n.payment_id for n in batch if n.payment_id)
                refs += tuple(ChatRef("payment", p) for p in payments if p)
                said.append(Said(chat, text, refs))
            return send(uow, said, now, self.settings.chat_history_keep)

    def idle_drafts(self, now: datetime) -> list[OutboundMessage]:
        """One reminder after a day without activity; expired after three (SPEC 10.4)."""
        with self.repository.unit_of_work() as uow:
            due = uow.drafts.due_for_reminder_or_expiry(now - self.settings.draft_reminder_after)
        out: list[OutboundMessage] = []
        for draft in due:
            try:
                out += self._idle(draft, now)
            except StaleDraftError:
                continue  # someone answered meanwhile
        return out

    def _idle(self, seen: BillDraft, now: datetime) -> list[OutboundMessage]:
        with self.repository.unit_of_work(lock=seen.conversation) as uow:
            draft = uow.drafts.get(seen.id)
            chat = uow.conversations.get(seen.conversation)
            adder = uow.people.get(seen.added_by)
            if draft != seen or chat is None or adder is None:
                return []
            turn = Turn(uow, self.ids, now, self.settings, adder, chat)
            ref = (ChatRef("draft", draft.id, draft.version),)
            if now - draft.last_activity_at >= self.settings.draft_expires_after:
                ended = finish(turn, draft, DraftState.EXPIRED)
                turn.show(f"The {draft.description} bill expired. Nothing was saved.")
                start_next(turn, ended)
            elif draft.reminded_at is None or draft.reminded_at < draft.last_activity_at:
                # not a change to the bill: same version, and no new activity
                uow.drafts.update(replace(draft, reminded_at=now), expected_version=draft.version)
                turn.show(_nudge(draft, adder.display_name), ref)
            return send(uow, [*turn.shown, *turn.elsewhere], now, self.settings.chat_history_keep)


def _nudge(draft: BillDraft, adder: str) -> str:
    """The one reminder, worded for what the draft waits for."""
    if draft.state is DraftState.AWAITING_PEOPLE:
        return f"Still waiting on the {draft.description} bill. {adder}, who's it with?"
    waiting = f"Still waiting on the {draft.description} bill."
    return f'{waiting} {adder}, say "yes" to save it, or "cancel".'
