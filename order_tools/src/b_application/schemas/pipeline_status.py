from dataclasses import dataclass, field

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.model.system.actor import Actor
from a_domain.types.enums import AuditAction
from a_domain.types.errors import SignInRequired


@dataclass
class PipelineStatus:
    """
    What one operation was asked and what its steps returned. Only the Pipeline writes these fields: a use case gets
    the values it needs as arguments. AuditTrail reads the request fields to write the operation's audit entry.
    """

    action: AuditAction
    """Which operation this is."""

    actor: Actor | None = None
    """Who operates: the actor of the request's verified token, or None when the request carried none."""

    order_id: str | None = None
    """The order the request named."""

    reason: str = ""
    """
    The cancel reason exactly as the request carried it. It may hold personal data, so it is stored only after the
    personal data filter.
    """

    request_id: str | None = None
    """The gateway's request id."""

    order: Order | None = None
    """OrderLookup: the order the actor may see. OrderCancellation: that order once the cancel is settled."""

    recipient: Recipient | None = None
    """RecipientLookup: the order's recipient, already masked. The unmasked recipient never reaches the status."""

    orders: list[Order] = field(default_factory=list)
    """OrderListing: the actor's own orders, newest first."""

    already_cancelled: bool = False
    """OrderCancellation: the order was cancelled before this request, so this request changed nothing."""

    def require_actor(self) -> Actor:
        if self.actor is None:
            raise SignInRequired

        return self.actor

    def require_order(self) -> Order:
        if self.order is None:
            raise RuntimeError("The operation ended without an order")

        return self.order

    def require_recipient(self) -> Recipient:
        if self.recipient is None:
            raise RuntimeError("The operation ended without the order's recipient")

        return self.recipient
