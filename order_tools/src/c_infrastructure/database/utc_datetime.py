from datetime import UTC, datetime
from typing import override

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """
    The column type of every datetime the database holds. SQLite keeps no zone, so a value is stored as UTC wall-clock
    time and loaded as an aware UTC datetime. A naive value is refused: nothing could tell which zone it meant.
    """

    impl = DateTime
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None

        if value.utcoffset() is None:
            raise ValueError(f"naive datetime {value.isoformat()} refused: store an aware datetime")

        return value.astimezone(UTC).replace(tzinfo=None)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None

        return value.replace(tzinfo=UTC)
