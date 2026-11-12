from pydantic import AwareDatetime
from pydantic.dataclasses import dataclass

from a_domain.model.system.actor import Actor
from a_domain.types.enums import AuditAction, AuditOutcome


@dataclass(frozen=True, kw_only=True)
class AuditEntry:
    """
    One entry of the audit log: who did what to which order, when, and how it ended. A refused request is an entry
    too. It holds none of the recipient's fields and no token.
    """

    occurred_at: AwareDatetime
    actor: Actor | None
    """Who operated, with the id of their token. None when no verified token came with the request."""

    action: AuditAction
    order_id: str | None
    outcome: AuditOutcome

    reason: str | None = None
    """The cancel reason the actor gave, with mobile numbers, email addresses, national IDs and card numbers removed."""

    detail: str | None = None
    """What a reader needs beside the outcome: the status that refused a cancel, or the kind of token failure."""

    request_id: str | None = None
    """The gateway's request id, so one call can be followed across the gateway, the agent and this service."""
