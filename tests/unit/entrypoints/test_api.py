"""The HTTP API around an orchestrator on the in-memory fakes (SPEC section 11, K3-K4)."""

import base64

import pytest
from fastapi.testclient import TestClient

from smartsplit.entrypoints.api import create_app
from tests.integration.world import FLAT, RAJ, SAM, YOU, World, flat, receipt

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client(world: World, max_image_bytes: int = 5_000_000) -> TestClient:
    app = create_app(world.bot, world.repository, api_token=TOKEN, max_image_bytes=max_image_bytes)
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
        "text": text,
    }
    return body | extra


def test_health_is_open_and_everything_else_needs_the_token() -> None:
    # K4
    api = client(World())
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.post("/v1/tick").status_code == 401
    assert api.post("/v1/tick", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/v1/people/x/rules").status_code == 401
    assert api.post("/v1/tick", headers=AUTH).json() == []


def test_the_api_refuses_to_start_without_a_token() -> None:
    world = World()
    with pytest.raises(ValueError, match="SMARTSPLIT_API_TOKEN"):
        create_app(world.bot, world.repository, api_token="", max_image_bytes=1)


def test_a_message_goes_through_the_orchestrator_and_retries_return_the_same() -> None:
    # K3, K5
    api = client(World())
    first = api.post("/v1/messages", headers=AUTH, json=message("help"))
    assert first.status_code == 200
    replies = first.json()
    assert replies[0]["conversation"] == {"channel": "whatsapp", "ref": "1203630@g.us"}
    assert replies[0]["recipient_id"] is None
    assert replies[0]["text"].startswith("Hi Flat 4B! Alex is in.")
    assert api.post("/v1/messages", headers=AUTH, json=message("help")).json() == replies


def test_a_receipt_photo_inline() -> None:
    api = client(World())
    api.post("/v1/messages", headers=AUTH, json=message("help", message_id="m0"))
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
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    world.say(RAJ, FLAT, "I don't drink milk")
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
            "source": "stated",
        }
    ]
    assert api.get("/v1/groups/nope/balances", headers=AUTH).status_code == 404
    assert api.get("/v1/people/nope/balances", headers=AUTH).status_code == 404
    assert api.get("/v1/people/nope/rules", headers=AUTH).status_code == 404
