"""The domain rules on their own: no database, no token, no MCP."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.model.system.actor import Actor
from a_domain.rules.order.access import OrderAccessRule
from a_domain.rules.order.cancellation import CancellationRule
from a_domain.rules.order.masking import RecipientMaskRule
from a_domain.rules.system.audit import AuditOutcomeRule
from a_domain.rules.system.sign_in import ActorRule
from a_domain.types.enums import AuditOutcome, OrderStatus, Role, SignInFailure
from a_domain.types.errors import CancelReasonRequired, OrderNotCancellable, TokenRefused

MEMBER = Actor(subject="member-alice", role=Role.MEMBER)
OTHER_MEMBER = Actor(subject="member-bob", role=Role.MEMBER)
CUSTOMER_SERVICE_ACTOR = Actor(subject="cs-agent-7", role=Role.CUSTOMER_SERVICE)


def order(status: OrderStatus, owner_id: str = "member-alice") -> Order:
    return Order(
        id="ORD-000001", owner_id=owner_id, status=status, total_amount=1180, created_at=datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    )


def test_member_sees_only_their_own_order():
    assert OrderAccessRule().apply(MEMBER, order(OrderStatus.PAID)) is True
    assert OrderAccessRule().apply(OTHER_MEMBER, order(OrderStatus.PAID)) is False


def test_customer_service_sees_every_order():
    assert OrderAccessRule().apply(CUSTOMER_SERVICE_ACTOR, order(OrderStatus.PAID)) is True


@pytest.mark.parametrize("status", [OrderStatus.PENDING_PAYMENT, OrderStatus.PAID])
def test_unshipped_order_is_cancelled(status):
    assert CancellationRule().apply(MEMBER, order(status), "") is True


@pytest.mark.parametrize("status", [OrderStatus.SHIPPED, OrderStatus.DELIVERED])
def test_shipped_or_delivered_order_is_refused_with_its_status(status):
    with pytest.raises(OrderNotCancellable) as refusal:
        CancellationRule().apply(MEMBER, order(status), "")

    assert (refusal.value.status, refusal.value.detail) == (status, status.value)


def test_cancelled_order_is_a_repeat_not_a_refusal():
    assert CancellationRule().apply(MEMBER, order(OrderStatus.CANCELLED), "") is False


@pytest.mark.parametrize("blank", ["", "   "])
def test_customer_service_must_give_a_reason(blank):
    with pytest.raises(CancelReasonRequired):
        CancellationRule().apply(CUSTOMER_SERVICE_ACTOR, order(OrderStatus.PAID), blank)


def test_reason_over_200_characters_is_invalid():
    with pytest.raises(ValidationError):
        CancellationRule().apply(CUSTOMER_SERVICE_ACTOR, order(OrderStatus.PAID), "很" * 201)


def test_order_refuses_a_cancel_its_status_does_not_allow():
    shipped = order(OrderStatus.SHIPPED)

    with pytest.raises(OrderNotCancellable):
        shipped.cancel(Role.MEMBER, None, now=datetime.now(UTC))

    assert (shipped.status, shipped.cancelled_at, shipped.cancelled_by_role) == (OrderStatus.SHIPPED, None, None)


def test_cancel_with_a_time_that_has_no_zone_changes_nothing():
    paid = order(OrderStatus.PAID)

    with pytest.raises(ValidationError):
        paid.cancel(Role.MEMBER, None, now=datetime(2026, 11, 2, 8, 30))

    assert (paid.status, paid.cancelled_at) == (OrderStatus.PAID, None)


def test_cancel_sets_the_status_and_the_cancel_fields_together():
    paid = order(OrderStatus.PAID)
    now = datetime(2026, 11, 2, 8, 30, tzinfo=UTC)

    paid.cancel(Role.CUSTOMER_SERVICE, "customer asked by phone", now=now)

    assert (paid.status, paid.cancelled_at, paid.cancelled_by_role, paid.cancel_reason) == (
        OrderStatus.CANCELLED,
        now,
        Role.CUSTOMER_SERVICE,
        "customer asked by phone",
    )


def test_only_unshipped_statuses_are_cancellable():
    assert OrderStatus.cancellable() == {OrderStatus.PENDING_PAYMENT, OrderStatus.PAID}


@pytest.fixture
def mask_rule(config) -> RecipientMaskRule:
    """The rule built from the masking settings that ship in config/appsetting.yaml, so the tests check those."""
    return RecipientMaskRule(**config.masking.model_dump())


def test_recipient_is_masked(mask_rule):
    recipient = Recipient(
        name="王小明", phone="0912-345-678", address="台北市大安區忠孝東路四段1號5樓", email="xiaoming.wang@example.com"
    )

    assert mask_rule.apply(recipient) == Recipient(
        name="王*明", phone="****-***-678", address="台北市大安區", email="x***@example.com"
    )


@pytest.mark.parametrize(("name", "masked"), [("王", "*"), ("王明", "王*"), ("歐陽小明", "歐**明")])
def test_name_mask_by_length(mask_rule, name, masked):
    assert mask_rule.apply(Recipient(name=name, phone="", address="", email="")).name == masked


def test_mask_hides_whole_what_it_cannot_parse(mask_rule):
    recipient = Recipient(name="Amy", phone="12", address="Flat 3, 10 Example Road", email="not-an-email")

    assert mask_rule.apply(recipient) == Recipient(name="A*y", phone="***", address="***", email="***")


@pytest.mark.parametrize(
    ("address", "area"),
    [
        ("106 台北市大安區忠孝東路四段1號", "台北市大安區"),
        ("高雄市前鎮區中山二路5號", "高雄市前鎮區"),
        ("桃園市平鎮區環南路100號", "桃園市平鎮區"),
        ("台南市新市區中正路1號", "台南市新市區"),
        ("新北市板橋區區運路1號", "新北市板橋區"),
        ("新竹縣竹北市光明六路10號", "新竹縣竹北市"),
        ("花蓮縣新城鄉大漢村1號", "花蓮縣新城鄉"),
        ("嘉義市中山路市場旁12號", "***"),
    ],
)
def test_address_keeps_only_the_city_and_the_whole_district(mask_rule, address, area):
    assert mask_rule.apply(Recipient(name="", phone="", address=address, email="")).address == area


@pytest.mark.parametrize(
    "email",
    ["w@example.com,other@example.com", "w@example.com;0912345678", "w@example.com (王小明)", "w@example.com王小明", "a@b@c.com"],
)
def test_email_field_that_holds_more_than_one_address_is_hidden_whole(mask_rule, email):
    assert mask_rule.apply(Recipient(name="", phone="", address="", email=email)).email == "***"


@pytest.mark.parametrize("phone", ["12", "678", "LINE: wang.xiaoming", "ext 02-2345-6789"])
def test_phone_that_is_not_a_plain_number_is_hidden_whole(mask_rule, phone):
    assert mask_rule.apply(Recipient(name="", phone=phone, address="", email="")).phone == "***"


@pytest.mark.parametrize(
    ("error", "already_cancelled", "expected"),
    [
        (None, False, (AuditOutcome.OK, None)),
        (None, True, (AuditOutcome.ALREADY_CANCELLED, None)),
        (OrderNotCancellable(OrderStatus.SHIPPED), False, (AuditOutcome.NOT_CANCELLABLE, "shipped")),
        (CancelReasonRequired(), False, (AuditOutcome.REASON_REQUIRED, None)),
        (KeyError("a bug"), False, (AuditOutcome.ERROR, "KeyError")),
        (asyncio.CancelledError(), False, (AuditOutcome.ERROR, "CancelledError")),
        (ValidationError.from_exception_data("limit", []), False, (AuditOutcome.INVALID_ARGUMENT, None)),
    ],
    ids=["finished", "repeat", "refused", "refused-no-detail", "bug", "cancelled", "invalid-argument"],
)
def test_audit_outcome_of_each_way_an_operation_ends(error, already_cancelled, expected):
    assert AuditOutcomeRule().apply(error, already_cancelled) == expected


def test_token_with_one_known_role_becomes_that_actor():
    actor = ActorRule().apply("cs-agent-7", ["customer_service", "warehouse"], "jti-1")

    assert (actor.subject, actor.role, actor.token_id) == ("cs-agent-7", Role.CUSTOMER_SERVICE, "jti-1")


@pytest.mark.parametrize("roles", [[], ["warehouse"], ["member", "customer_service"]], ids=["empty", "unknown", "ambiguous"])
def test_token_without_exactly_one_known_role_is_refused(roles):
    with pytest.raises(TokenRefused) as refusal:
        ActorRule().apply("member-alice", roles, None)

    assert refusal.value.detail == SignInFailure.NO_SINGLE_KNOWN_ROLE
