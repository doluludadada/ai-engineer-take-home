from pydantic.dataclasses import dataclass

from a_domain.model.order.order import Order
from a_domain.model.system.actor import Actor


@dataclass(frozen=True)
class OrderAccessRule:
    """Whether the actor may see the order: customer service sees every order, a member only their own."""

    def apply(self, actor: Actor, order: Order) -> bool:
        if actor.role.sees_every_order:
            return True

        return order.owner_id == actor.subject
