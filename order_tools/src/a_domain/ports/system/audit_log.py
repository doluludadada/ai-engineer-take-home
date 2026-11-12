from typing import Protocol

from a_domain.model.system.audit_entry import AuditEntry


class IAuditLog(Protocol):
    """The audit log. Entries are only ever added: nothing changes or removes one."""

    async def record(self, entry: AuditEntry) -> None: ...
