from pydantic import AwareDatetime, ConfigDict, NonNegativeInt, validate_call
from pydantic.dataclasses import dataclass

from a_domain.types.enums import OrderStatus, Role
from a_domain.types.errors import OrderNotCancellable
from a_domain.types.ids import OrderId, UserId


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class Order:
    """One order: who placed it, its status and amount, and, once cancelled, when, by which role and why."""

    # It carries none of the recipient's fields, so a tool answers with it as it is: who receives it is a Recipient,
    # which only the operation that answers with one order loads, masked. The three cancel fields are set together by
    # the one cancel that goes through and never change after. They say which role cancelled and not who: the audit
    # log holds who.

    id: OrderId
    owner_id: UserId
    """The member who placed it."""

    status: OrderStatus
    total_amount: NonNegativeInt
    created_at: AwareDatetime

    cancelled_at: AwareDatetime | None = None
    cancelled_by_role: Role | None = None
    cancel_reason: str | None = None
    """
    What the actor gave as the reason, with mobile numbers, email addresses, national IDs and card numbers removed.
    None when a member gave none.
    """

    @validate_call
    def cancel(self, role: Role, reason: str | None, *, now: AwareDatetime) -> None:
        if not self.status.can_cancel:
            raise OrderNotCancellable(self.status)

        self.status = OrderStatus.CANCELLED
        self.cancelled_at = now
        self.cancelled_by_role = role
        self.cancel_reason = reason
