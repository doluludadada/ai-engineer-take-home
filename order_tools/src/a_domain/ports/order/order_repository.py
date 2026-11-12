from typing import Protocol

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.types.ids import OrderId, UserId


class IOrderRepository(Protocol):
    async def get(self, order_id: OrderId) -> Order | None: ...

    async def get_recipient(self, order_id: OrderId) -> Recipient | None:
        """The order's recipient, unmasked. Only the step that masks it calls this."""
        ...

    async def list_for_owner(self, owner_id: UserId, limit: int) -> list[Order]:
        """The owner's orders, newest first."""
        ...

    async def add(self, order: Order, recipient: Recipient) -> None: ...

    async def cancel(self, order: Order) -> bool:
        """
        Stores a cancelled order's status and cancel fields, but only while the stored status still allows a cancel.
        Returns False, and changes nothing, when it no longer does: the order was cancelled or shipped since the caller
        read it. So of any number of requests for one order, exactly one stores its cancel.
        """
        ...
