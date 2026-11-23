"""The HTTP API around an orchestrator on the in-memory fakes (SPEC section 11, K3-K4)."""

import base64
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smartsplit.adapters.fakes.agent import call
from smartsplit.entrypoints.api import create_app
from tests.integration.world import FLAT, RAJ, SAM, YOU, World, calling, flat, receipt

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client(
    world: World, max_image_bytes: int = 5_000_000, ready: Callable[[], bool] = lambda: True
) -> TestClient:
    app = create_app(
        world.bot,
        world.repository,
        api_token=TOKEN,
        max_image_bytes=max_image_bytes,
        ready=ready,
    )
    return TestClient(app)


def message(text: str | None = None, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "message_id": "wamid.1",
        "conversation": {"channel": "whatsapp", "ref": "1203630@g.us"},
        "conversation_kind": "group",
        "conversation_name": "Flat 4B",
        "sender_ref": "+919876500001",
        "sender_phone": "+919876500001",
        "sender_name": "Alex",
        "addressed_to_bot": True,
        "reply_to_bot": False,
        "text": text,
    }
    return body | extra


def test_health_is_open_and_everything_else_needs_the_token() -> None:
    # K4
    api = client(World())
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.post("/v1/tick").status_code == 401
    wrong = api.post("/v1/tick", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.headers["WWW-Authenticate"] == "Bearer"
    assert api.get("/v1/people/x/rules").status_code == 401
    assert api.post("/v1/tick", headers=AUTH).json()["messages"] == []


def test_the_api_refuses_to_start_without_a_token() -> None:
    world = World()
    for token in ("", "   "):
        with pytest.raises(ValueError, match="SMARTSPLIT_API_TOKEN"):
            create_app(
                world.bot, world.repository, api_token=token, max_image_bytes=1, ready=lambda: True
            )


def test_a_message_goes_through_the_orchestrator_and_retries_return_the_same() -> None:
    # K3, K5
    api = client(World())
    first = api.post("/v1/messages", headers=AUTH, json=message("help"))
    assert first.status_code == 200
    replies = first.json()
    assert replies[0]["conversation"] == {"channel": "whatsapp", "ref": "1203630@g.us"}
    assert replies[0]["recipient_id"] is None
    assert replies[0]["text"].startswith("Hi Flat 4B! I split bills")
    assert api.post("/v1/messages", headers=AUTH, json=message("help")).json() == replies


def test_a_receipt_photo_inline() -> None:
    world = World()
    api = client(world)
    api.post("/v1/messages", headers=AUTH, json=message("help", message_id="m0"))
    world.agent.queue(call("start_receipt"))
    data = base64.b64encode(receipt("restaurant_tip").data).decode()
    photo = message(message_id="m1", image={"mime_type": "image/jpeg", "data_base64": data})
    replies = api.post("/v1/messages", headers=AUTH, json=photo).json()
    assert replies[-1]["text"].startswith("Toit, ₹2,047.00, paid by Alex.")


def test_images_are_size_limited_and_must_be_base64() -> None:
    api = client(World(), max_image_bytes=10)
    big = message(
        image={"mime_type": "image/jpeg", "data_base64": base64.b64encode(b"x" * 11).decode()}
    )
    assert api.post("/v1/messages", headers=AUTH, json=big).status_code == 413
    bad = message(image={"mime_type": "image/jpeg", "data_base64": "not base64!"})
    assert api.post("/v1/messages", headers=AUTH, json=bad).status_code == 422
    assert api.post("/v1/messages", headers=AUTH, json={"text": "hi"}).status_code == 422


def ids(world: World) -> tuple[str, str]:
    with world.repository.unit_of_work() as uow:
        you, sam = uow.people.by_phone(YOU.phone), uow.people.by_phone(SAM.phone)
        group = uow.groups.by_channel_ref(world.message(YOU, FLAT).conversation)
        assert you is not None and sam is not None and group is not None
        return group.id, you.id


def test_operator_reads() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "rent", call("add_manual_bill", description="rent", amount="3000"))
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    world.say(RAJ, FLAT, "no milk", call("add_rule", subject="me", item="milk", kind="exclude"))
    group_id, you_id = ids(world)
    api = client(world)
    group = api.get(f"/v1/groups/{group_id}/balances", headers=AUTH).json()
    assert group["name"] == "Flat 4B"
    assert [b["cents"] for b in group["balances"]] == [200000, -100000, -100000]
    assert len(group["settle_up"]) == 2
    mine = api.get(f"/v1/people/{you_id}/balances", headers=AUTH).json()
    assert {w["name"]: w["cents"] for w in mine["with"]} == {"Sam": 100000, "Raj": 100000}
    assert mine["with"][0]["by_context"] == [{"context": "Flat 4B", "cents": 100000}]
    with world.repository.unit_of_work() as uow:
        raj = uow.people.by_phone(RAJ.phone)
        assert raj is not None
    rules = api.get(f"/v1/people/{raj.id}/rules", headers=AUTH).json()["rules"]
    assert rules == [
        {
            "item": "milk",
            "kind": "exclude",
            "scope": "Flat 4B",
            "author_id": raj.id,
            "author": "Raj",
            "source": "stated",
        }
    ]
    assert api.get("/v1/groups/nope/balances", headers=AUTH).status_code == 404
    assert api.get("/v1/people/nope/balances", headers=AUTH).status_code == 404
    assert api.get("/v1/people/nope/rules", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "field",
    ["message_id", "sender_ref", "sender_name", "conversation_name", "sender_phone"],
)
def test_control_characters_are_refused(field: str) -> None:
    api = client(World())
    response = api.post("/v1/messages", headers=AUTH, json=message("hi", **{field: "a\u0000b"}))
    assert response.status_code == 422


def test_control_characters_in_nested_fields_are_refused() -> None:
    api = client(World())
    nested: list[dict[str, Any]] = [
        {"conversation": {"channel": "whatsapp", "ref": "a\u0000"}},
        {"image": {"mime_type": "image/\u0000", "data_base64": ""}},
        {"contact": {"name": "Priya", "phone": "+91\u0000"}},
        {"event": {"kind": "participant_left", "subject_ref": "\u0000"}},
        {"text": "hi\u0000"},
    ]
    for extra in nested:
        assert api.post("/v1/messages", headers=AUTH, json=message(**extra)).status_code == 422
    assert api.post("/v1/messages", headers=AUTH, json=message("two\nlines")).status_code == 200


def test_bodies_are_size_limited_before_they_are_read() -> None:
    api = client(World(), max_image_bytes=10)
    huge = "x" * 200_000
    body = message(image={"mime_type": "image/jpeg", "data_base64": huge})
    assert api.post("/v1/messages", headers=AUTH, json=body).status_code == 413
    no_length = api.post(
        "/v1/messages", headers=AUTH | {"Transfer-Encoding": "chunked"}, content=iter([b"{}"])
    )
    assert no_length.status_code == 411


def test_rules_in_someones_notes_name_the_owner() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(
        YOU, None, "Sam never", calling("add_rule", subject="@Sam", item="dessert", kind="exclude")
    )
    world.say(YOU, None, "yes", calling("confirm_pending", action="@A"))
    with world.repository.unit_of_work() as uow:
        sam = uow.people.by_phone(SAM.phone)
        assert sam is not None
    rules = client(world).get(f"/v1/people/{sam.id}/rules", headers=AUTH).json()["rules"]
    assert [(r["item"], r["scope"], r["author"]) for r in rules] == [
        ("dessert", "Alex's notes", "Alex")
    ]
