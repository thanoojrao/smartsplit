"""FastAPI app (SPEC section 11): the gateway's webhook, the timer, and operator reads.

Every `/v1/*` route needs `Authorization: Bearer <SMARTSPLIT_API_TOKEN>`, compared in
constant time; `/healthz` and `/readyz` are open. Each message logs one line without content
(SPEC 12.4). The app gets a ready Orchestrator and Repository, so it
holds no business logic: requests are translated to domain messages and back.
"""

import base64
import binascii
import hmac
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import (
    ChatEvent,
    ContactAttachment,
    ImageAttachment,
    InboundMessage,
    Mention,
    OutboundMessage,
)
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import Repository
from smartsplit.services import Orchestrator
from smartsplit.services.orchestrator import TurnReport
from smartsplit.services.reports import group_report, person_report, rules_report

NO_CONTROL = r"^[^\x00-\x1f\x7f]*$"
"""Ids, names and numbers never contain control characters (Postgres can't store NUL)."""
NO_NUL = r"^[^\x00]*$"
"""Message text may have line breaks, never NUL."""


def _line(max_length: int, min_length: int = 0) -> Any:
    return Field(min_length=min_length, max_length=max_length, pattern=NO_CONTROL)


BODY_ALLOWANCE = 100_000
"""Room for everything but the image in a message body (text, names, JSON)."""
RETRY_AFTER_SECONDS = 5
"""What a busy chat's 503 tells the gateway to wait before retrying (SPEC 12.2)."""

log = logging.getLogger("smartsplit.turns")


class ConversationIn(BaseModel):
    """Which chat, as the gateway names it."""

    channel: str = _line(64, 1)
    ref: str = _line(256, 1)


class ImageIn(BaseModel):
    """A photo inline; its size is checked against SMARTSPLIT_MAX_IMAGE_BYTES."""

    mime_type: str = _line(64, 1)
    data_base64: str


class ContactIn(BaseModel):
    """A shared contact card."""

    name: str = _line(200)
    phone: str = _line(40)


class EventIn(BaseModel):
    """Someone left the group chat (`subject_ref` is who), or the bot was added to it."""

    kind: Literal["participant_left", "bot_added"]
    subject_ref: str | None = Field(default=None, max_length=256, pattern=NO_CONTROL)


class MentionIn(BaseModel):
    """Someone the text mentions as "@<ref>"; the phone when the gateway knows it."""

    ref: str = _line(256, 1)
    name: str = _line(200)
    phone: str | None = Field(default=None, max_length=40, pattern=NO_CONTROL)


class MessageIn(BaseModel):
    """An `InboundMessage` in snake_case JSON (CONTRACTS section 5)."""

    message_id: str = _line(256, 1)
    conversation: ConversationIn
    conversation_kind: ConversationKind
    conversation_name: str | None = Field(default=None, max_length=200, pattern=NO_CONTROL)
    sender_ref: str = _line(256, 1)
    sender_alt_ref: str | None = Field(default=None, max_length=256, pattern=NO_CONTROL)
    sender_phone: str | None = Field(default=None, max_length=40, pattern=NO_CONTROL)
    sender_name: str = _line(200)
    addressed_to_bot: bool
    reply_to_bot: bool
    quoted_text: str | None = Field(default=None, max_length=2_000, pattern=NO_NUL)
    mentions: list[MentionIn] = Field(default_factory=list, max_length=50)
    text: str | None = Field(default=None, max_length=65_536, pattern=NO_NUL)
    image: ImageIn | None = None
    contact: ContactIn | None = None
    event: EventIn | None = None


class MessageOut(BaseModel):
    """A reply to deliver: to a group chat (`recipient_id` null) or someone's own chat."""

    conversation: ConversationIn
    recipient_id: str | None
    text: str


class TickOut(BaseModel):
    """One tick's messages; acknowledge the batch once they are sent (SPEC 10.8)."""

    batch_id: str
    messages: list[MessageOut]


def create_app(
    orchestrator: Orchestrator,
    repository: Repository,
    *,
    api_token: str,
    max_image_bytes: int,
    ready: Callable[[], bool],
) -> FastAPI:
    """The API around one orchestrator; refuses an empty token rather than run open."""
    if not api_token.strip():
        raise ValueError("SMARTSPLIT_API_TOKEN must be set to run the API")
    expected = api_token.encode()
    body_limit = (max_image_bytes * 4) // 3 + BODY_ALLOWANCE
    bearer = HTTPBearer(auto_error=False)

    def authorized(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        given = credentials.credentials.encode() if credentials else b""
        if not hmac.compare_digest(given, expected):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "bad or missing token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    app = FastAPI(title="SmartSplit", docs_url=None, redoc_url=None, openapi_url=None)
    guarded = [Depends(authorized)]

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuse an oversized body before reading it (SPEC 12.4)."""
        length = request.headers.get("content-length")
        if request.method == "POST" and (length is None or not length.isdigit()):
            return JSONResponse({"detail": "length required"}, status.HTTP_411_LENGTH_REQUIRED)
        if length is not None and length.isdigit() and int(length) > body_limit:
            return JSONResponse({"detail": "request too large"}, status.HTTP_413_CONTENT_TOO_LARGE)
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        """Ready when the database answers and its schema is the newest."""
        if ready():
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "not ready"}, status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.post("/v1/messages", dependencies=guarded)
    def messages(body: MessageIn) -> list[MessageOut]:
        outcome = orchestrator.handle(_inbound(body, max_image_bytes))
        log_turn(outcome.report)
        if outcome.busy:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "chat busy, retry",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        return _out(outcome.replies)

    @app.post("/v1/tick", dependencies=guarded)
    def tick() -> TickOut:
        batch = orchestrator.tick()
        return TickOut(batch_id=batch.id, messages=_out(batch.messages))

    @app.post(
        "/v1/tick/{batch_id}/ack",
        dependencies=guarded,
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def ack(batch_id: str) -> None:
        if not orchestrator.ack(batch_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such batch")

    @app.get("/v1/groups/{group_id}/balances", dependencies=guarded)
    def group_balances(group_id: str) -> dict[str, object]:
        with repository.unit_of_work() as uow:
            report = group_report(uow, group_id)
        return asdict(_found(report))

    @app.get("/v1/people/{person_id}/balances", dependencies=guarded)
    def person_balances(person_id: str) -> dict[str, object]:
        with repository.unit_of_work() as uow:
            report = person_report(uow, person_id)
        return {"person_id": person_id, "with": [asdict(r) for r in _found(report)]}

    @app.get("/v1/people/{person_id}/rules", dependencies=guarded)
    def person_rules(person_id: str) -> dict[str, object]:
        with repository.unit_of_work() as uow:
            report = rules_report(uow, person_id)
        return {"person_id": person_id, "rules": [asdict(r) for r in _found(report)]}

    return app


def _found[T](report: T | None) -> T:
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return report


def _inbound(body: MessageIn, max_image_bytes: int) -> InboundMessage:
    image = None
    if body.image is not None:
        try:
            data = base64.b64decode(body.image.data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad base64") from error
        if len(data) > max_image_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "image too large")
        image = ImageAttachment(body.image.mime_type, data)
    return InboundMessage(
        message_id=body.message_id,
        conversation=ConversationKey(body.conversation.channel, body.conversation.ref),
        conversation_kind=body.conversation_kind,
        conversation_name=body.conversation_name,
        sender_ref=body.sender_ref,
        sender_alt_ref=body.sender_alt_ref,
        sender_phone=body.sender_phone,
        sender_name=body.sender_name,
        addressed_to_bot=body.addressed_to_bot,
        reply_to_bot=body.reply_to_bot,
        quoted_text=body.quoted_text,
        mentions=tuple(Mention(m.ref, m.name, m.phone) for m in body.mentions),
        text=body.text,
        image=image,
        contact=ContactAttachment(body.contact.name, body.contact.phone) if body.contact else None,
        event=ChatEvent(body.event.kind, body.event.subject_ref) if body.event else None,
    )


def log_turn(report: TurnReport) -> None:
    """The per-turn line: no text, ids or numbers, only what helps debugging (SPEC 12.4)."""
    tools = ",".join(f"{name}:{'ok' if ok else 'error'}" for name, ok in report.tools) or "-"
    usage = report.usage
    log.info(
        "turn chat=%s outcome=%s steps=%d tools=%s tokens=in:%d,cache_read:%d,cache_write:%d,"
        "out:%d seconds=%.2f",
        report.chat,
        report.outcome,
        report.steps,
        tools,
        usage.input_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.output_tokens,
        report.seconds,
    )
    if report.install_nearly_spent:
        log.warning("over 80%% of today's model calls for the whole install are used")


def _out(messages: Sequence[OutboundMessage]) -> list[MessageOut]:
    return [
        MessageOut(
            conversation=ConversationIn(channel=m.conversation.channel, ref=m.conversation.ref),
            recipient_id=m.recipient_id,
            text=m.text,
        )
        for m in messages
    ]
