from typing import Self

from pydantic import BaseModel

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from b_application.schemas.pipeline_status import PipelineStatus


class OrderResponse(BaseModel):
    """One order and its recipient, whose name, phone, address and email are masked."""

    order: Order
    recipient: Recipient

    @classmethod
    def from_status(cls, status: PipelineStatus) -> Self:
        return cls(order=status.require_order(), recipient=status.require_recipient())


class OrderListResponse(BaseModel):
    """The signed-in person's own orders, newest first."""

    orders: list[Order]

    @classmethod
    def from_status(cls, status: PipelineStatus) -> Self:
        return cls(orders=status.orders)


class CancellationResponse(BaseModel):
    """The order after the cancel. already_cancelled is true when an earlier request had cancelled it."""

    order: Order
    already_cancelled: bool

    @classmethod
    def from_status(cls, status: PipelineStatus) -> Self:
        return cls(order=status.require_order(), already_cancelled=status.already_cancelled)
