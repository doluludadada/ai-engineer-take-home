import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from a_domain.model.system.audit_entry import AuditEntry
from a_domain.ports.system.audit_log import IAuditLog
from a_domain.ports.system.clock import IClock
from a_domain.ports.system.personal_data_filter import IPersonalDataFilter
from a_domain.rules.system.audit import AuditOutcomeRule
from b_application.schemas.pipeline_status import PipelineStatus


class AuditTrail:
    """
    Use Case: Write one audit entry for an operation, however it ends. The operation runs inside `execute`, so a
    finished, a refused, a failed and a cancelled operation each leave an entry: who, when, which order, what, and the
    outcome. The write is shielded, so whatever cancels the operation cannot also cancel the entry about it. The cancel
    reason goes through the personal data filter first, and none of the recipient's fields is written.
    """

    def __init__(self, audit_log: IAuditLog, personal_data_filter: IPersonalDataFilter, clock: IClock) -> None:
        self._audit_log = audit_log
        self._personal_data_filter = personal_data_filter
        self._clock = clock
        self._outcome_rule = AuditOutcomeRule()

    @asynccontextmanager
    async def execute(self, status: PipelineStatus) -> AsyncGenerator[None]:
        error: BaseException | None = None

        try:
            yield
        except BaseException as raised:
            error = raised
            raise
        finally:
            outcome, detail = self._outcome_rule.apply(error, status.already_cancelled)
            entry = AuditEntry(
                occurred_at=self._clock.now(),
                actor=status.actor,
                action=status.action,
                order_id=status.order_id,
                outcome=outcome,
                reason=self._personal_data_filter.remove(status.reason.strip()) or None,
                detail=detail,
                request_id=status.request_id,
            )
            await asyncio.shield(self._audit_log.record(entry))
