"""FastAPI app (SPEC section 11): the gateway's webhook, the timer, and operator reads.

Every `/v1/*` route needs `Authorization: Bearer <SMARTSPLIT_API_TOKEN>`, compared in
constant time; `/healthz` is open. The app gets a ready Orchestrator and Repository, so it
holds no business logic: requests are translated to domain messages and back.
"""

import base64
import binascii
import hmac
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import (
    ChatEvent,
    ContactAttachment,
    ImageAttachment,
    InboundMessage,
    OutboundMessage,
)
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import Repository
from smartsplit.services import Orchestrator
from smartsplit.services.reports import group_report, person_report, rules_report


class ConversationIn(BaseModel):
    channel: str = Field(min_length=1, max_length=64)
    ref: str = Field(min_length=1, max_length=256)


class ImageIn(BaseModel):
    mime_type: str = Field(max_length=64)
    data_base64: str


class ContactIn(BaseModel):
    name: str = Field(max_length=200)
    phone: str = Field(max_length=40)


class EventIn(BaseModel):
    kind: Literal["participant_left"]
    subject_ref: str = Field(min_length=1, max_length=256)


class MessageIn(BaseModel):
    """An `InboundMessage` in snake_case JSON (CONTRACTS section 5)."""

    message_id: str = Field(min_length=1, max_length=256)
    conversation: ConversationIn
    conversation_kind: ConversationKind
    conversation_name: str | None = Field(default=None, max_length=200)
    sender_ref: str = Field(min_length=1, max_length=256)
    sender_alt_ref: str | None = Field(default=None, max_length=256)
    sender_phone: str | None = Field(default=None, max_length=40)
    sender_name: str = Field(default="", max_length=200)
    addressed_to_bot: bool = False
    reply_to_bot: bool = False
    text: str | None = Field(default=None, max_length=4000)
    image: ImageIn | None = None
    contact: ContactIn | None = None
    event: EventIn | None = None


class MessageOut(BaseModel):
    conversation: ConversationIn
    recipient_id: str | None
    text: str


def create_app(
    orchestrator: Orchestrator, repository: Repository, *, api_token: str, max_image_bytes: int
) -> FastAPI:
    """The API around one orchestrator; refuses an empty token rather than run open."""
    if not api_token:
        raise ValueError("SMARTSPLIT_API_TOKEN must be set to run the API")
    expected = api_token.encode()
    bearer = HTTPBearer(auto_error=False)

    def authorized(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        given = credentials.credentials.encode() if credentials else b""
        if not hmac.compare_digest(given, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad or missing token")

    app = FastAPI(title="SmartSplit", docs_url=None, redoc_url=None, openapi_url=None)
    guarded = [Depends(authorized)]

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/messages", dependencies=guarded)
    def messages(body: MessageIn) -> list[MessageOut]:
        return _out(orchestrator.handle(_inbound(body, max_image_bytes)))

    @app.post("/v1/tick", dependencies=guarded)
    def tick() -> list[MessageOut]:
        return _out(orchestrator.tick())

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
        if len(body.image.data_base64) > (max_image_bytes * 4) // 3 + 4:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "image too large")
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
        text=body.text,
        image=image,
        contact=ContactAttachment(body.contact.name, body.contact.phone) if body.contact else None,
        event=ChatEvent(body.event.kind, body.event.subject_ref) if body.event else None,
    )


def _out(messages: list[OutboundMessage]) -> list[MessageOut]:
    return [
        MessageOut(
            conversation=ConversationIn(channel=m.conversation.channel, ref=m.conversation.ref),
            recipient_id=m.recipient_id,
            text=m.text,
        )
        for m in messages
    ]
