from pydantic import validate_call
from pydantic.dataclasses import dataclass

from a_domain.model.order.order import Order
from a_domain.model.system.actor import Actor
from a_domain.types.enums import OrderStatus
from a_domain.types.errors import CancelReasonRequired, OrderNotCancellable
from a_domain.types.values import CancelReason


@dataclass(frozen=True)
class CancellationRule:
    """
    Whether a cancel request changes the order. True: cancel it now. False: it is already cancelled, so the request is
    a repeat, and it is answered with the first cancellation instead of being run again. A refusal raises:
    CancelReasonRequired when customer service gives no reason, OrderNotCancellable once the order has shipped.

    The actor is already known to see the order (OrderAccessRule), so no answer here tells them anything new about it.
    """

    @validate_call
    def apply(self, actor: Actor, order: Order, reason: CancelReason) -> bool:
        if actor.role.must_give_cancel_reason and not reason.strip():
            raise CancelReasonRequired

        if order.status == OrderStatus.CANCELLED:
            return False

        if not order.status.can_cancel:
            raise OrderNotCancellable(order.status)

        return True
