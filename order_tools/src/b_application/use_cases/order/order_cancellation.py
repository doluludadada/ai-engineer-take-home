from a_domain.model.order.order import Order
from a_domain.model.system.actor import Actor
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.ports.system.clock import IClock
from a_domain.ports.system.personal_data_filter import IPersonalDataFilter
from a_domain.rules.order.cancellation import CancellationRule
from a_domain.types.errors import OrderNotFound


class OrderCancellation:
    """
    Use Case: Cancel an order the actor may see, once. It returns the order as it is afterwards and whether it was
    already cancelled before this request.

    The agent or the gateway may send the same cancel twice. CancellationRule answers a repeat with the cancel the
    order already holds. Two requests that arrive together both read the order as cancellable, so the repository's
    guarded update decides: one stores its cancel, and the other is told nothing changed, reads the order again and is
    answered like any later repeat. The reason is stored after the personal data filter.
    """

    def __init__(self, order_repository: IOrderRepository, personal_data_filter: IPersonalDataFilter, clock: IClock) -> None:
        self._order_repository = order_repository
        self._personal_data_filter = personal_data_filter
        self._clock = clock
        self._cancellation_rule = CancellationRule()

    async def execute(self, actor: Actor, order: Order, reason: str) -> tuple[Order, bool]:
        if not self._cancellation_rule.apply(actor, order, reason):
            return order, True

        order.cancel(actor.role, self._personal_data_filter.remove(reason.strip()) or None, now=self._clock.now())

        if await self._order_repository.cancel(order):
            return order, False

        stored = await self._order_repository.get(order.id)

        if stored is None:
            raise OrderNotFound(order.id)

        return await self.execute(actor, stored, reason)
