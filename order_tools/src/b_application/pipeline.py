from dataclasses import dataclass

from a_domain.model.system.actor import Actor
from a_domain.types.enums import AuditAction
from a_domain.types.ids import OrderId
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.order.order_cancellation import OrderCancellation
from b_application.use_cases.order.order_listing import OrderListing
from b_application.use_cases.order.order_lookup import OrderLookup
from b_application.use_cases.order.recipient_lookup import RecipientLookup
from b_application.use_cases.system.audit_trail import AuditTrail
from b_application.use_cases.system.sign_in import SignIn


@dataclass(slots=True)
class Pipeline:
    """
    Every operation the MCP tools start. Each line of an operation names one step and the field that keeps what it
    returns.

    Only get_order loads a recipient, and it keeps the masked one. Listing and cancelling work on Order alone, which
    carries none of the recipient's fields.

    The three order operations take the actor, never a user id: the tool server passes the actor of the request's
    verified token, or None when there is none, and the operation then refuses with SignInRequired. Each runs inside
    AuditTrail.execute, so every call leaves one audit entry, a refused one included, unless the audit write itself fails.
    """

    sign_in: SignIn
    order_lookup: OrderLookup
    recipient_lookup: RecipientLookup
    order_listing: OrderListing
    order_cancellation: OrderCancellation
    audit_trail: AuditTrail

    async def sign_in_with_token(self, token: str) -> Actor:
        return await self.sign_in.execute(token)

    async def get_order(self, actor: Actor | None, order_id: OrderId, request_id: str | None = None) -> PipelineStatus:
        status = PipelineStatus(action=AuditAction.GET_ORDER, actor=actor, order_id=order_id, request_id=request_id)

        async with self.audit_trail.execute(status):
            status.order = await self.order_lookup.execute(status.require_actor(), order_id)
            status.recipient = await self.recipient_lookup.execute(status.order)

        return status

    async def list_my_orders(self, actor: Actor | None, limit: int, request_id: str | None = None) -> PipelineStatus:
        status = PipelineStatus(action=AuditAction.LIST_MY_ORDERS, actor=actor, request_id=request_id)

        async with self.audit_trail.execute(status):
            status.orders = await self.order_listing.execute(status.require_actor(), limit)

        return status

    async def cancel_order(
        self, actor: Actor | None, order_id: OrderId, reason: str = "", request_id: str | None = None
    ) -> PipelineStatus:
        status = PipelineStatus(action=AuditAction.CANCEL_ORDER, actor=actor, order_id=order_id, reason=reason, request_id=request_id)

        async with self.audit_trail.execute(status):
            status.order = await self.order_lookup.execute(status.require_actor(), order_id)
            status.order, status.already_cancelled = await self.order_cancellation.execute(
                status.require_actor(), status.order, reason
            )

        return status
