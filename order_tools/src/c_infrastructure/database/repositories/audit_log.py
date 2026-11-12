from typing import override

from a_domain.model.system.audit_entry import AuditEntry
from a_domain.ports.system.audit_log import IAuditLog
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.audit_log_dto import AuditLogDTO


class AuditLog(IAuditLog):
    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def record(self, entry: AuditEntry) -> None:
        async with self._db.session() as session:
            session.add(AuditLogDTO.from_domain(entry))
            await session.commit()
