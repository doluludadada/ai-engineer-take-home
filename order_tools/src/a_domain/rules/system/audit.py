from pydantic import ValidationError
from pydantic.dataclasses import dataclass

from a_domain.types.enums import AuditOutcome
from a_domain.types.errors import Refusal


@dataclass(frozen=True)
class AuditOutcomeRule:
    """
    How an operation ended, for its audit entry: the outcome and the detail beside it. `error` is what the operation
    raised, or None when it finished. An operation cancelled from outside, such as at shutdown, raises too, so it is
    recorded as an error.
    """

    def apply(self, error: BaseException | None, already_cancelled: bool) -> tuple[AuditOutcome, str | None]:
        if error is None:
            return (AuditOutcome.ALREADY_CANCELLED if already_cancelled else AuditOutcome.OK), None

        if isinstance(error, Refusal):
            return error.outcome, error.detail

        if isinstance(error, ValidationError):
            return AuditOutcome.INVALID_ARGUMENT, None

        return AuditOutcome.ERROR, type(error).__name__
