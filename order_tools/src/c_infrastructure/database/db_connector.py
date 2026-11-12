from contextlib import AbstractAsyncContextManager
from typing import override

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from a_domain.ports.system.database_connector import IDatabaseConnector
from b_application.config.app_config import AppConfig
from c_infrastructure.database.models.audit_log_dto import AuditLogDTO, make_append_only
from c_infrastructure.database.models.order_dto import OrderDTO


class DatabaseConnector(IDatabaseConnector[AsyncSession]):
    """
    The local SQLite file. Every session opens its own connection and closes it (NullPool), so no connection is ever
    shared between two requests. A write that finds another connection writing waits `db_busy_timeout_seconds` for it.
    A database error never quotes the values of the statement that failed (hide_parameters), so a cancel reason or a
    token id cannot reach a log or a tool answer through an error text.
    """

    def __init__(self, config: AppConfig) -> None:
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{config.db}",
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"timeout": config.db_busy_timeout_seconds},
        )
        self._session_factory = async_sessionmaker(bind=self._engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        self._tables = [SQLModel.metadata.tables[dto.__tablename__] for dto in (OrderDTO, AuditLogDTO)]

    @override
    async def init_db(self) -> None:
        async with self._engine.connect() as connection:
            # WAL lets a read go on while another connection writes. The mode is saved in the file.
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")

        async with self._engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all, tables=self._tables)
            await make_append_only(connection)

    @override
    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._session_factory()
