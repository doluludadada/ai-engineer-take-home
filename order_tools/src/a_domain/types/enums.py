from enum import StrEnum, auto


class Role(StrEnum):
    """A member or customer service."""

    # The value is the text the token's `roles` claim carries.

    MEMBER = auto()
    """A customer. Sees and cancels only their own orders."""

    CUSTOMER_SERVICE = auto()
    """Customer service. Sees and cancels any order, and says why when cancelling one."""

    @property
    def sees_every_order(self) -> bool:
        match self:
            case Role.CUSTOMER_SERVICE:
                return True
            case Role.MEMBER:
                return False

    @property
    def must_give_cancel_reason(self) -> bool:
        match self:
            case Role.CUSTOMER_SERVICE:
                return True
            case Role.MEMBER:
                return False


class OrderStatus(StrEnum):
    PENDING_PAYMENT = auto()
    """Placed and not yet paid."""

    PAID = auto()
    """Paid and still in the warehouse."""

    SHIPPED = auto()
    """Handed to the carrier. From here the way back is a return, not a cancel."""

    DELIVERED = auto()
    """Received by the customer."""

    CANCELLED = auto()
    """Cancelled before it shipped. It never changes again."""

    @property
    def next_statuses(self) -> frozenset[OrderStatus]:
        match self:
            case OrderStatus.PENDING_PAYMENT:
                return frozenset({OrderStatus.PAID, OrderStatus.CANCELLED})
            case OrderStatus.PAID:
                return frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED})
            case OrderStatus.SHIPPED:
                return frozenset({OrderStatus.DELIVERED})
            case _:
                return frozenset()

    @property
    def can_cancel(self) -> bool:
        return OrderStatus.CANCELLED in self.next_statuses

    @classmethod
    def cancellable(cls) -> frozenset[OrderStatus]:
        """Every status a cancel may start from. The repository's guarded update names exactly these."""
        return frozenset(status for status in cls if status.can_cancel)


class SigningAlgorithm(StrEnum):
    """
    The signature algorithms a token may use, by their JWT names. Every member signs with a private key and verifies
    with a public one, so no setting can choose an unsigned token (none) or a shared secret (HS256).
    """

    RS256 = "RS256"
    RS384 = "RS384"
    RS512 = "RS512"


class TokenClaim(StrEnum):
    """The claims this service reads from an SSO token, by their JWT names."""

    SUBJECT = "sub"
    ROLES = "roles"
    EXPIRES_AT = "exp"
    AUDIENCE = "aud"
    ISSUER = "iss"
    TOKEN_ID = "jti"

    @property
    def required(self) -> bool:
        """Whether a token without this claim is refused. The token id only helps the audit log, so it may be absent."""
        match self:
            case TokenClaim.TOKEN_ID:
                return False
            case _:
                return True


class SignInFailure(StrEnum):
    """
    Why this service refuses a request whose token passed, or never reached, the signature check. A token that fails
    the check itself is recorded with the JWT library's own error name, such as ExpiredSignatureError.
    """

    NO_VERIFIED_TOKEN = auto()
    """The request reached an operation with no verified token at all."""

    INVALID_SUBJECT = auto()
    """The subject claim is empty."""

    INVALID_ROLES = auto()
    """The roles claim is not a list."""

    NO_SINGLE_KNOWN_ROLE = auto()
    """The roles claim names none of the roles this service knows, or more than one."""


class AuditAction(StrEnum):
    SIGN_IN = auto()
    GET_ORDER = auto()
    LIST_MY_ORDERS = auto()
    CANCEL_ORDER = auto()


class AuditOutcome(StrEnum):
    OK = auto()

    ALREADY_CANCELLED = auto()
    """A cancel of an order that was already cancelled. Answered with the first cancellation, and nothing changed."""

    UNAUTHENTICATED = auto()
    NOT_FOUND = auto()
    NOT_CANCELLABLE = auto()
    REASON_REQUIRED = auto()
    INVALID_ARGUMENT = auto()
    """
    A pydantic check failed inside the Pipeline: an argument outside its type's limits, or a stored value a model
    refuses. A tool never answers it for an argument: the MCP SDK checks the same types before a tool runs.
    """

    ERROR = auto()
    """A failure that is not a refusal: a bug, an outage or an operation cancelled from outside."""

    @property
    def is_refusal(self) -> bool:
        """Whether a tool answers this outcome with an error and a sentence for the model."""
        match self:
            case AuditOutcome.OK | AuditOutcome.ALREADY_CANCELLED | AuditOutcome.INVALID_ARGUMENT | AuditOutcome.ERROR:
                return False
            case _:
                return True

    @property
    def error_code(self) -> str:
        """The code a tool returns for a refused request, such as NOT_FOUND. The caller branches on it."""
        return self.value.upper()
