from datetime import UTC, datetime
from typing import override

from a_domain.ports.system.clock import IClock


class SystemClock(IClock):
    @override
    def now(self) -> datetime:
        return datetime.now(UTC)
