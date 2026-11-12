from contextlib import AbstractAsyncContextManager
from typing import Protocol


class IDatabaseConnector[Session](Protocol):
    """
    The database the repositories share. Each unit of work gets its own session. The infrastructure names the session
    type, so this port never imports a database library.
    """

    async def init_db(self) -> None:
        """Creates the tables that do not exist yet, and makes the audit log refuse updates and deletes."""
        ...

    def session(self) -> AbstractAsyncContextManager[Session]: ...
