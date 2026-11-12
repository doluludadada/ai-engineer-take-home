from typing import Self

from pydantic import BaseModel, model_validator

from a_domain.types.enums import AuditOutcome, OrderStatus
from a_domain.types.values import NonEmptyText


class TextsConfig(BaseModel):
    """
    The sentences written for the model: what each tool and argument is for, and what a tool answers when it refuses.
    They are in the customers' language and change without a code change.
    """

    server_instructions: NonEmptyText

    get_order_description: NonEmptyText
    list_my_orders_description: NonEmptyText
    cancel_order_description: NonEmptyText

    order_id_argument: NonEmptyText
    """What the order_id argument of get_order and cancel_order is."""

    limit_argument: NonEmptyText
    reason_argument: NonEmptyText

    refusals: dict[AuditOutcome, NonEmptyText]
    """The answer for each refusal, by its outcome."""

    not_cancellable: dict[OrderStatus, NonEmptyText]
    """A more exact answer for a refused cancel, by the order's status. A status not listed gets `refusals`' answer."""

    @model_validator(mode="after")
    def _every_refusal_has_a_text(self) -> Self:
        missing = [outcome.value for outcome in AuditOutcome if outcome.is_refusal and outcome not in self.refusals]

        if missing:
            raise ValueError(f"texts.refusals has no sentence for: {', '.join(missing)}")

        return self
