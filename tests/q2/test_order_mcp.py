"""The tools as an agent reaches them: the published schemas, and real HTTP calls with a bearer token."""

import asyncio
import threading
import time
from collections.abc import Iterator

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from a_domain.types.enums import AuditAction, AuditOutcome, OrderStatus, Role
from b_application.config.texts_config import TextsConfig
from d_presentation.mcp_tools.schemas import CancellationResponse
from d_presentation.mcp_tools.server import answer, build_server

IDENTITY_ARGUMENTS = {"user_id": "member-bob", "sub": "member-bob", "owner_id": "member-bob", "role": "customer_service"}


@pytest.fixture
def mcp_server(pipeline, config, world):
    return build_server(pipeline, config)


@pytest.fixture
def mcp_url(mcp_server) -> Iterator[str]:
    app = mcp_server.streamable_http_app(host="127.0.0.1")
    http = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not http.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    port = http.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/mcp"
    http.should_exit = True
    thread.join(timeout=10)


async def call(url: str, token: str, tool: str, arguments: dict, **headers: str):
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", **headers}) as http,
        Client(streamable_http_client(url, http_client=http)) as client,
    ):
        return await client.call_tool(tool, arguments)


async def raw_post(url: str, headers: dict[str, str]) -> httpx2.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with httpx2.AsyncClient() as http:
        return await http.post(url, json=body, headers={"Accept": "application/json, text/event-stream", **headers})


def argument_schema(tool, name: str) -> dict:
    """One argument's schema with its shared definition filled in: a domain type such as OrderId is published once under $defs."""
    schema = dict(tool.input_schema["properties"][name])
    reference = schema.pop("$ref", None)

    if reference is None:
        return schema

    return {**tool.input_schema["$defs"][reference.rsplit("/", 1)[-1]], **schema}


async def test_published_input_schemas(mcp_server):
    async with Client(mcp_server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(tools) == {"get_order", "list_my_orders", "cancel_order"}
    assert set(tools["get_order"].input_schema["properties"]) == {"order_id"}
    order_id = argument_schema(tools["get_order"], "order_id")
    assert order_id["pattern"] == r"^ORD-[0-9]{6}$"
    assert "訂單編號" in order_id["description"]
    limit = argument_schema(tools["list_my_orders"], "limit")
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 10)
    assert set(tools["cancel_order"].input_schema["properties"]) == {"order_id", "reason"}
    assert argument_schema(tools["cancel_order"], "reason")["maxLength"] == 200
    assert tools["cancel_order"].input_schema["required"] == ["order_id"]
    assert tools["cancel_order"].annotations.idempotent_hint is True
    assert tools["cancel_order"].annotations.destructive_hint is True
    assert tools["get_order"].annotations.read_only_hint is True
    assert tools["list_my_orders"].annotations.read_only_hint is True
    for tool in tools.values():
        assert tool.description
        assert tool.output_schema is not None
        assert not set(tool.input_schema["properties"]) & set(IDENTITY_ARGUMENTS)


async def test_tool_call_without_verified_identity_is_unauthenticated(mcp_server, world, audit_entries):
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_order", {"order_id": world.alice_paid, **IDENTITY_ARGUMENTS})

    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "UNAUTHENTICATED"
    assert [entry.outcome for entry in audit_entries()] == [AuditOutcome.UNAUTHENTICATED]


async def test_http_request_without_bearer_is_refused(mcp_url):
    response = await raw_post(mcp_url, {})

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_http_request_with_invalid_bearer_is_refused_and_audited(mcp_url, mint, attacker_key, audit_entries):
    expired = mint(exp=int(time.time()) - 3600, iat=int(time.time()) - 4000)
    forged = mint(key=attacker_key)

    for token in (expired, forged, "not-a-jwt"):
        assert (await raw_post(mcp_url, {"Authorization": f"Bearer {token}"})).status_code == 401

    entries = audit_entries()
    assert [(entry.action, entry.outcome, entry.actor_subject) for entry in entries] == [
        (AuditAction.SIGN_IN, AuditOutcome.UNAUTHENTICATED, None)
    ] * 3
    assert all(token not in repr(entries) for token in (expired, forged))


async def test_http_member_gets_own_order_with_masked_pii(mcp_url, mint, world, audit_entries):
    result = await call(
        mcp_url,
        mint(world.alice.subject, jti="alice-token"),
        "get_order",
        {"order_id": world.alice_paid},
        **{"X-Request-Id": "gw-req-42"},
    )

    assert result.is_error is False
    assert result.structured_content["order"]["id"] == world.alice_paid
    assert result.structured_content["recipient"]["name"] == "王*明"
    assert world.alice.recipient.phone not in result.content[0].text
    [entry] = audit_entries()
    assert (entry.actor_subject, entry.actor_role, entry.outcome) == (world.alice.subject, Role.MEMBER, AuditOutcome.OK)
    assert (entry.request_id, entry.token_id) == ("gw-req-42", "alice-token")


async def test_http_request_id_is_cut_to_the_configured_length_and_has_a_fallback(mcp_url, mint, world, audit_entries, config):
    token = mint(world.alice.subject)

    await call(mcp_url, token, "get_order", {"order_id": world.alice_paid}, **{"X-Request-Id": "r" * 500})
    await call(mcp_url, token, "get_order", {"order_id": world.alice_paid})

    with_header, without_header = audit_entries()
    assert with_header.request_id == "r" * config.request_id_max_length
    assert without_header.request_id


async def test_http_identity_cannot_be_claimed_through_arguments(mcp_url, mint, world):
    alice = mint(world.alice.subject)

    read = await call(mcp_url, alice, "get_order", {"order_id": world.bob_paid, **IDENTITY_ARGUMENTS})
    cancel = await call(mcp_url, alice, "cancel_order", {"order_id": world.bob_paid, **IDENTITY_ARGUMENTS})
    listed = await call(mcp_url, alice, "list_my_orders", {"limit": 50, **IDENTITY_ARGUMENTS})

    missing = await call(mcp_url, alice, "get_order", {"order_id": world.missing})

    assert read.is_error and read.structured_content["error"]["code"] == "NOT_FOUND"
    assert missing.structured_content == read.structured_content
    assert world.bob_paid not in read.structured_content["error"]["message"]
    assert cancel.is_error and cancel.structured_content["error"]["code"] == "NOT_FOUND"
    listed_ids = {order["id"] for order in listed.structured_content["orders"]}
    assert world.bob_paid not in listed_ids
    assert world.alice_paid in listed_ids


async def test_http_repeated_cancel_returns_already_cancelled(mcp_url, mint, world):
    token = mint(world.alice.subject)

    first = await call(mcp_url, token, "cancel_order", {"order_id": world.alice_paid})
    retry = await call(mcp_url, token, "cancel_order", {"order_id": world.alice_paid})

    assert first.structured_content["already_cancelled"] is False
    assert retry.structured_content["already_cancelled"] is True
    assert retry.structured_content["order"] == first.structured_content["order"]


async def test_http_shipped_order_cancel_is_refused_with_return_advice(mcp_url, mint, world):
    shipped = await call(mcp_url, mint(world.alice.subject), "cancel_order", {"order_id": world.alice_shipped})

    assert shipped.is_error and shipped.structured_content["error"]["code"] == "NOT_CANCELLABLE"
    assert "退貨" in shipped.structured_content["error"]["message"]


async def test_http_argument_outside_the_schema_never_reaches_the_tool(mcp_url, mint, world, audit_entries):
    result = await call(mcp_url, mint(world.alice.subject), "list_my_orders", {"limit": 51})

    assert result.is_error is True
    assert result.structured_content is None
    assert audit_entries() == []


async def test_operation_a_client_stops_waiting_for_still_finishes(pipeline, world, config, audit_entries):
    waiting = asyncio.ensure_future(
        answer(pipeline.cancel_order(world.member_alice, world.alice_paid), CancellationResponse, config.texts)
    )
    await asyncio.sleep(0)
    waiting.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiting
    for _ in range(500):
        if audit_entries():
            break
        await asyncio.sleep(0.01)

    [entry] = audit_entries()
    assert (entry.action, entry.outcome) == (AuditAction.CANCEL_ORDER, AuditOutcome.OK)
    assert (await pipeline.get_order(world.member_alice, world.alice_paid)).order.status is OrderStatus.CANCELLED


async def test_http_customer_service_must_give_a_reason(mcp_url, mint, world):
    customer_service = mint("cs-agent-7", [Role.CUSTOMER_SERVICE.value])

    refused = await call(mcp_url, customer_service, "cancel_order", {"order_id": world.bob_paid})
    cancelled = await call(mcp_url, customer_service, "cancel_order", {"order_id": world.bob_paid, "reason": "客戶來電要求取消"})

    assert refused.is_error and refused.structured_content["error"]["code"] == "REASON_REQUIRED"
    assert cancelled.structured_content["order"]["cancelled_by_role"] == "customer_service"


def test_settings_must_hold_a_sentence_for_every_refusal(config):
    texts = config.texts.model_dump()
    del texts["refusals"][AuditOutcome.NOT_FOUND]

    with pytest.raises(ValidationError, match="not_found"):
        TextsConfig.model_validate(texts)
