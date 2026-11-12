from datetime import datetime
from typing import ClassVar, Self

from sqlalchemy import Column, String
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import Field, SQLModel

from a_domain.model.system.audit_entry import AuditEntry
from a_domain.types.enums import AuditAction, AuditOutcome, Role
from c_infrastructure.database.utc_datetime import UtcDateTime


class AuditLogDTO(SQLModel, table=True):
    __tablename__: ClassVar[str] = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    occurred_at: datetime = Field(sa_type=UtcDateTime)
    actor_subject: str | None = None
    actor_role: Role | None = Field(default=None, sa_column=Column(String, nullable=True))
    token_id: str | None = None
    action: AuditAction = Field(sa_column=Column(String, nullable=False))
    order_id: str | None = None
    outcome: AuditOutcome = Field(sa_column=Column(String, nullable=False))
    reason: str | None = None
    detail: str | None = None
    request_id: str | None = None

    @classmethod
    def from_domain(cls, entry: AuditEntry) -> Self:
        actor = entry.actor

        return cls(
            occurred_at=entry.occurred_at,
            actor_subject=actor.subject if actor else None,
            actor_role=actor.role if actor else None,
            token_id=actor.token_id if actor else None,
            action=entry.action,
            order_id=entry.order_id,
            outcome=entry.outcome,
            reason=entry.reason,
            detail=entry.detail,
            request_id=entry.request_id,
        )


async def make_append_only(connection: AsyncConnection) -> None:
    """
    Makes the database itself refuse an UPDATE or a DELETE on the audit log, so neither statement from a bug in this
    service can change an entry. Someone with the database's own credentials still can: a production deployment would
    also ship the entries elsewhere, which this service does not do.
    """
    for change in ("UPDATE", "DELETE"):
        await connection.exec_driver_sql(
            f"CREATE TRIGGER IF NOT EXISTS audit_log_no_{change.lower()} BEFORE {change} ON audit_log "
            "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
        )
