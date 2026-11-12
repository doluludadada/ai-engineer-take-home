from a_domain.types.enums import AuditOutcome, OrderStatus, SignInFailure


class Refusal(Exception):
    """
    A request the service refuses. `outcome` is what the audit log records and what the tool's error code is made of,
    and `detail` is the audit entry's machine-readable note. The sentence the model reads for it comes from the settings
    (texts.refusals), so the message here is for a developer and never reaches the model.
    """

    outcome: AuditOutcome

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class SignInRequired(Refusal):
    """The request reached an operation without a verified SSO token."""

    outcome = AuditOutcome.UNAUTHENTICATED

    def __init__(self) -> None:
        super().__init__("No verified SSO token came with the request", SignInFailure.NO_VERIFIED_TOKEN)


class TokenRefused(Refusal):
    """The SSO token failed verification. `detail` names the failure and never repeats the token."""

    outcome = AuditOutcome.UNAUTHENTICATED

    def __init__(self, detail: str) -> None:
        super().__init__(f"The SSO token was refused: {detail}", detail)


class OrderNotFound(Refusal):
    """
    The order does not exist, or the actor may not see it. Both get this one answer, so nobody can use the tools to
    find out which order numbers exist.
    """

    outcome = AuditOutcome.NOT_FOUND

    def __init__(self, order_id: str) -> None:
        super().__init__(f"Order {order_id} does not exist or is not the actor's to see")


class OrderNotCancellable(Refusal):
    """The order already left the warehouse, so it is returned, not cancelled."""

    outcome = AuditOutcome.NOT_CANCELLABLE

    def __init__(self, status: OrderStatus) -> None:
        super().__init__(f"An order that is {status.value} cannot be cancelled", status.value)
        self.status = status


class CancelReasonRequired(Refusal):
    """Customer service cancelled an order without saying why."""

    outcome = AuditOutcome.REASON_REQUIRED

    def __init__(self) -> None:
        super().__init__("Customer service must give a reason to cancel an order")
