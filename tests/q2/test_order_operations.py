"""The three order operations through the Pipeline, on a real SQLite file: what a caller gets and what the tables hold."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone

import anyio
import pytest
from pydantic import ValidationError

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.types.enums import AuditAction, AuditOutcome, OrderStatus, Role
from a_domain.types.errors import CancelReasonRequired, OrderNotCancellable, OrderNotFound, SignInRequired
from d_presentation.mcp_tools.schemas import OrderListResponse, OrderResponse


def stored_cancel(config, order_id: str) -> tuple:
    """The order's status and cancel columns as the SQLite file holds them."""
    with closing(sqlite3.connect(config.db)) as connection:
        return connection.execute("SELECT status, cancelled_by_role, cancel_reason FROM orders WHERE id = ?", (order_id,)).fetchone()


def cancel_of(order) -> tuple:
    return order.cancelled_at, order.cancelled_by_role, order.cancel_reason


def outcomes(audit_entries, action: AuditAction, order_id: str | None = None) -> list[str]:
    return [entry.outcome for entry in audit_entries() if entry.action == action and entry.order_id == order_id]


async def status_of(pipeline, actor, order_id: str) -> OrderStatus:
    return (await pipeline.get_order(actor, order_id)).order.status


async def test_member_reading_another_members_order_gets_not_found(pipeline, world, audit_entries):
    with pytest.raises(OrderNotFound):
        await pipeline.get_order(world.member_alice, world.bob_paid)
    with pytest.raises(OrderNotFound):
        await pipeline.get_order(world.member_alice, world.missing)

    assert outcomes(audit_entries, AuditAction.GET_ORDER, world.bob_paid) == [AuditOutcome.NOT_FOUND]
    assert outcomes(audit_entries, AuditAction.GET_ORDER, world.missing) == [AuditOutcome.NOT_FOUND]


async def test_order_number_of_the_wrong_shape_is_invalid(pipeline, world, audit_entries):
    with pytest.raises(ValidationError):
        await pipeline.get_order(world.member_alice, "order-1")

    assert outcomes(audit_entries, AuditAction.GET_ORDER, "order-1") == [AuditOutcome.INVALID_ARGUMENT]


async def test_member_reads_own_order(pipeline, world):
    order = (await pipeline.get_order(world.member_alice, world.alice_paid)).order

    assert (order.id, order.status) == (world.alice_paid, OrderStatus.PAID)


async def test_customer_service_reads_any_order(pipeline, world):
    assert (await pipeline.get_order(world.customer_service, world.bob_paid)).order.id == world.bob_paid


async def test_list_my_orders_returns_only_the_actors_orders_newest_first(pipeline, world):
    alice_orders = [order.id for order in (await pipeline.list_my_orders(world.member_alice, 10)).orders]
    bob_orders = [order.id for order in (await pipeline.list_my_orders(world.member_bob, 10)).orders]

    assert alice_orders == [world.alice_delivered, world.alice_shipped, world.alice_paid, world.alice_pending]
    assert bob_orders == [world.bob_paid]


async def test_customer_service_lists_their_own_orders_which_are_none(pipeline, world):
    assert (await pipeline.list_my_orders(world.customer_service, 10)).orders == []


async def test_list_my_orders_respects_limit(pipeline, world):
    assert len((await pipeline.list_my_orders(world.member_alice, 2)).orders) == 2


@pytest.mark.parametrize("bad_limit", [0, 51])
async def test_list_my_orders_limit_out_of_range_is_invalid(pipeline, world, audit_entries, bad_limit):
    with pytest.raises(ValidationError):
        await pipeline.list_my_orders(world.member_alice, bad_limit)

    assert outcomes(audit_entries, AuditAction.LIST_MY_ORDERS) == [AuditOutcome.INVALID_ARGUMENT]


async def test_member_cancels_own_paid_order(pipeline, world, config):
    before = datetime.now(UTC)
    status = await pipeline.cancel_order(world.member_alice, world.alice_paid)

    assert status.already_cancelled is False
    assert status.order.status is OrderStatus.CANCELLED
    assert status.order.cancelled_by_role is Role.MEMBER
    assert before <= status.order.cancelled_at <= datetime.now(UTC)
    assert stored_cancel(config, world.alice_paid) == ("cancelled", "member", None)
    assert await status_of(pipeline, world.member_alice, world.alice_paid) is OrderStatus.CANCELLED


async def test_member_cannot_cancel_another_members_order(pipeline, world):
    with pytest.raises(OrderNotFound):
        await pipeline.cancel_order(world.member_alice, world.bob_paid)

    assert await status_of(pipeline, world.member_bob, world.bob_paid) is OrderStatus.PAID


async def test_shipped_order_cancel_is_refused(pipeline, world, config):
    with pytest.raises(OrderNotCancellable) as refusal:
        await pipeline.cancel_order(world.member_alice, world.alice_shipped)

    assert refusal.value.status is OrderStatus.SHIPPED
    assert await status_of(pipeline, world.member_alice, world.alice_shipped) is OrderStatus.SHIPPED
    assert stored_cancel(config, world.alice_shipped) == ("shipped", None, None)


async def test_member_cancels_own_unpaid_order(pipeline, world):
    assert (await pipeline.cancel_order(world.member_alice, world.alice_pending)).order.status is OrderStatus.CANCELLED


async def test_delivered_order_cancel_is_refused(pipeline, world):
    with pytest.raises(OrderNotCancellable) as refusal:
        await pipeline.cancel_order(world.member_alice, world.alice_delivered)

    assert refusal.value.status is OrderStatus.DELIVERED


@pytest.mark.parametrize("blank", ["", "   "])
async def test_customer_service_cancel_without_reason_is_refused(pipeline, world, blank):
    with pytest.raises(CancelReasonRequired):
        await pipeline.cancel_order(world.customer_service, world.bob_paid, blank)

    assert await status_of(pipeline, world.customer_service, world.bob_paid) is OrderStatus.PAID


async def test_customer_service_cancels_with_reason(pipeline, world):
    order = (await pipeline.cancel_order(world.customer_service, world.bob_paid, "客戶來電要求取消")).order

    assert (order.cancelled_by_role, order.cancel_reason) == (Role.CUSTOMER_SERVICE, "客戶來電要求取消")


async def test_overlong_reason_is_invalid(pipeline, world):
    with pytest.raises(ValidationError):
        await pipeline.cancel_order(world.customer_service, world.bob_paid, "很" * 201)

    assert await status_of(pipeline, world.customer_service, world.bob_paid) is OrderStatus.PAID


async def test_repeated_cancel_request_is_safe(pipeline, world, audit_entries, config):
    first = await pipeline.cancel_order(world.member_alice, world.alice_paid, "買錯了")
    second = await pipeline.cancel_order(world.member_alice, world.alice_paid, "買錯了")

    assert (first.already_cancelled, second.already_cancelled) == (False, True)
    assert cancel_of(second.order) == cancel_of(first.order)
    assert stored_cancel(config, world.alice_paid) == ("cancelled", "member", "買錯了")
    assert outcomes(audit_entries, AuditAction.CANCEL_ORDER, world.alice_paid) == [AuditOutcome.OK, AuditOutcome.ALREADY_CANCELLED]


async def test_repeated_cancel_by_another_actor_returns_the_first_cancel(pipeline, world):
    first = await pipeline.cancel_order(world.customer_service, world.bob_paid, "客戶來電要求取消")
    retry = await pipeline.cancel_order(world.member_bob, world.bob_paid)

    assert retry.already_cancelled is True
    assert cancel_of(retry.order) == cancel_of(first.order)
    assert retry.order.cancelled_by_role is Role.CUSTOMER_SERVICE


async def test_cancel_requests_arriving_together_store_one_cancel(pipeline, world, audit_entries, config):
    attempts = 8

    results = await asyncio.gather(*(pipeline.cancel_order(world.member_alice, world.alice_paid, "重試") for _ in range(attempts)))

    assert sorted(status.already_cancelled for status in results) == [False] + [True] * (attempts - 1)
    assert len({cancel_of(status.order) for status in results}) == 1
    assert stored_cancel(config, world.alice_paid) == ("cancelled", "member", "重試")
    recorded = outcomes(audit_entries, AuditAction.CANCEL_ORDER, world.alice_paid)
    assert (recorded.count(AuditOutcome.OK), recorded.count(AuditOutcome.ALREADY_CANCELLED)) == (1, attempts - 1)


async def test_tool_answer_masks_the_recipient(pipeline, world):
    answer = OrderResponse.from_status(await pipeline.get_order(world.customer_service, world.alice_paid))

    assert answer.recipient == Recipient(name="王*明", phone="****-***-678", address="台北市大安區", email="x***@example.com")
    recipient = world.alice.recipient
    for raw in (recipient.name, recipient.phone, recipient.address, recipient.email):
        assert raw not in answer.model_dump_json()


async def test_order_list_carries_no_recipient_data(pipeline, world):
    listed = OrderListResponse.from_status(await pipeline.list_my_orders(world.member_alice, 10)).model_dump_json()

    recipient = world.alice.recipient
    for raw in (recipient.name, "王", recipient.phone, "678", "台北市", recipient.email, "example.com"):
        assert raw not in listed


async def test_cancel_reason_and_audit_rows_hold_no_phone_or_email(pipeline, world, config):
    recipient = world.alice.recipient
    await pipeline.get_order(world.member_alice, world.alice_paid)
    await pipeline.list_my_orders(world.member_alice, 10)
    await pipeline.cancel_order(world.customer_service, world.alice_pending, f"王小明來電 {recipient.phone}，Email {recipient.email}")
    with pytest.raises(OrderNotFound):
        await pipeline.get_order(world.member_bob, world.alice_paid)

    with closing(sqlite3.connect(config.db)) as connection:
        audit_rows = connection.execute("SELECT * FROM audit_log").fetchall()
        cancel_reasons = connection.execute("SELECT cancel_reason FROM orders").fetchall()

    assert len(audit_rows) == 4
    for raw in (recipient.phone, "345-678", recipient.address, "忠孝東路", recipient.email):
        assert raw not in repr(audit_rows)
        assert raw not in repr(cancel_reasons)
    masked_reason = "王小明來電 [PHONE_1]，Email [EMAIL_1]"
    assert masked_reason in repr(audit_rows)
    assert masked_reason in repr(cancel_reasons)


async def test_audit_records_who_when_what_and_refusals(pipeline, world, audit_entries):
    before = datetime.now(UTC)
    await pipeline.cancel_order(world.member_alice, world.alice_paid)
    with pytest.raises(OrderNotFound):
        await pipeline.get_order(world.member_bob, world.alice_paid)
    with pytest.raises(OrderNotCancellable):
        await pipeline.cancel_order(world.member_alice, world.alice_shipped)
    with pytest.raises(CancelReasonRequired):
        await pipeline.cancel_order(world.customer_service, world.bob_paid)

    entries = audit_entries()
    assert [(entry.actor_subject, entry.actor_role, entry.action, entry.order_id, entry.outcome) for entry in entries] == [
        (world.alice.subject, Role.MEMBER, AuditAction.CANCEL_ORDER, world.alice_paid, AuditOutcome.OK),
        (world.bob.subject, Role.MEMBER, AuditAction.GET_ORDER, world.alice_paid, AuditOutcome.NOT_FOUND),
        (world.alice.subject, Role.MEMBER, AuditAction.CANCEL_ORDER, world.alice_shipped, AuditOutcome.NOT_CANCELLABLE),
        ("cs-agent-7", Role.CUSTOMER_SERVICE, AuditAction.CANCEL_ORDER, world.bob_paid, AuditOutcome.REASON_REQUIRED),
    ]
    assert entries[0].token_id == world.member_alice.token_id
    assert entries[2].detail == OrderStatus.SHIPPED.value
    assert all(before <= datetime.fromisoformat(entry.occurred_at).replace(tzinfo=UTC) <= datetime.now(UTC) for entry in entries)


async def test_call_without_actor_is_refused_and_audited(pipeline, world, audit_entries):
    with pytest.raises(SignInRequired):
        await pipeline.get_order(None, world.alice_paid)

    [entry] = audit_entries()
    assert (entry.actor_subject, entry.outcome, entry.order_id) == (None, AuditOutcome.UNAUTHENTICATED, world.alice_paid)


async def test_operation_cancelled_from_outside_is_audited_as_an_error(pipeline, world, audit_entries):
    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as group:
            group.start_soon(pipeline.cancel_order, world.member_alice, world.alice_paid)
            await asyncio.sleep(0)
            scope.cancel()

    for _ in range(500):
        if audit_entries():
            break
        await asyncio.sleep(0.01)

    [entry] = audit_entries()
    assert (entry.action, entry.outcome, entry.detail) == (AuditAction.CANCEL_ORDER, AuditOutcome.ERROR, "CancelledError")
    assert await status_of(pipeline, world.member_alice, world.alice_paid) is OrderStatus.PAID


async def test_audit_log_is_append_only(pipeline, world, config):
    await pipeline.get_order(world.member_alice, world.alice_paid)

    with closing(sqlite3.connect(config.db)) as connection:
        for statement in ("UPDATE audit_log SET outcome = 'ok'", "DELETE FROM audit_log"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                connection.execute(statement)


async def test_order_time_in_another_zone_is_stored_as_the_same_instant(order_repository, world, config):
    taipei_morning = datetime(2026, 11, 2, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    await order_repository.add(
        Order(id="ORD-000099", owner_id=world.alice.subject, status=OrderStatus.PAID, total_amount=1, created_at=taipei_morning),
        world.alice.recipient,
    )

    stored = await order_repository.get("ORD-000099")
    assert (stored.created_at, stored.created_at.utcoffset()) == (taipei_morning, timedelta(0))
    with closing(sqlite3.connect(config.db)) as connection:
        assert (
            connection.execute("SELECT created_at FROM orders WHERE id = 'ORD-000099'").fetchone()[0].startswith("2026-11-02 01:00:00")
        )
