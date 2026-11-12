from pydantic import validate_call

from a_domain.model.order.order import Order
from a_domain.model.system.actor import Actor
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.rules.order.access import OrderAccessRule
from a_domain.types.errors import OrderNotFound
from a_domain.types.ids import OrderId


class OrderLookup:
    """
    Use Case: Load the order the actor named, if they may see it (OrderAccessRule). An order that does not exist and
    an order of somebody else raise the same OrderNotFound.
    """

    def __init__(self, order_repository: IOrderRepository) -> None:
        self._order_repository = order_repository
        self._access_rule = OrderAccessRule()

    @validate_call
    async def execute(self, actor: Actor, order_id: OrderId) -> Order:
        order = await self._order_repository.get(order_id)

        if order is None or not self._access_rule.apply(actor, order):
            raise OrderNotFound(order_id)

        return order
