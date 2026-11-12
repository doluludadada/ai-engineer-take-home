from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.rules.order.masking import RecipientMaskRule
from a_domain.types.errors import OrderNotFound
from b_application.config.app_config import AppConfig


class RecipientLookup:
    """
    Use Case: Load the recipient of an order the actor may see, and return it masked (RecipientMaskRule). The unmasked
    recipient exists only inside this step, so no later step, answer or log can hold it.
    """

    def __init__(self, order_repository: IOrderRepository, config: AppConfig) -> None:
        self._order_repository = order_repository
        self._mask_rule = RecipientMaskRule(
            mask_character=config.masking.mask_character,
            hidden_text=config.masking.hidden_text,
            phone_visible_digits=config.masking.phone_visible_digits,
            address_area_pattern=config.masking.address_area_pattern,
        )

    async def execute(self, order: Order) -> Recipient:
        recipient = await self._order_repository.get_recipient(order.id)

        if recipient is None:
            raise OrderNotFound(order.id)

        return self._mask_rule.apply(recipient)
