from datetime import datetime
from typing import ClassVar, Self

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.types.enums import OrderStatus, Role
from c_infrastructure.database.utc_datetime import UtcDateTime


class OrderDTO(SQLModel, table=True):
    """
    One order with its recipient. A query loads the whole row: to_domain leaves the recipient columns out, and only
    to_recipient, which get_recipient calls, turns them into a Recipient.
    """

    __tablename__: ClassVar[str] = "orders"

    id: str = Field(primary_key=True)
    owner_id: str = Field(index=True)
    status: OrderStatus = Field(sa_column=Column(String, nullable=False))
    total_amount: int
    created_at: datetime = Field(sa_type=UtcDateTime)

    cancelled_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
    cancelled_by_role: Role | None = Field(default=None, sa_column=Column(String, nullable=True))
    cancel_reason: str | None = None

    recipient_name: str
    recipient_phone: str
    recipient_address: str
    recipient_email: str

    @classmethod
    def from_domain(cls, order: Order, recipient: Recipient) -> Self:
        return cls(
            id=order.id,
            owner_id=order.owner_id,
            status=order.status,
            total_amount=order.total_amount,
            created_at=order.created_at,
            cancelled_at=order.cancelled_at,
            cancelled_by_role=order.cancelled_by_role,
            cancel_reason=order.cancel_reason,
            recipient_name=recipient.name,
            recipient_phone=recipient.phone,
            recipient_address=recipient.address,
            recipient_email=recipient.email,
        )

    def to_domain(self) -> Order:
        return Order(
            id=self.id,
            owner_id=self.owner_id,
            status=OrderStatus(self.status),
            total_amount=self.total_amount,
            created_at=self.created_at,
            cancelled_at=self.cancelled_at,
            cancelled_by_role=Role(self.cancelled_by_role) if self.cancelled_by_role else None,
            cancel_reason=self.cancel_reason,
        )

    def to_recipient(self) -> Recipient:
        return Recipient(
            name=self.recipient_name, phone=self.recipient_phone, address=self.recipient_address, email=self.recipient_email
        )
