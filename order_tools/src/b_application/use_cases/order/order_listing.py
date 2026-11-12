from pydantic import validate_call

from a_domain.model.order.order import Order
from a_domain.model.system.actor import Actor
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.types.values import ListLimit


class OrderListing:
    """Use Case: Load the actor's own orders, newest first. Customer service gets their own too, which is none."""

    def __init__(self, order_repository: IOrderRepository) -> None:
        self._order_repository = order_repository

    @validate_call
    async def execute(self, actor: Actor, limit: ListLimit) -> list[Order]:
        return await self._order_repository.list_for_owner(actor.subject, limit)
