from datetime import datetime
from typing import Protocol


class IClock(Protocol):
    def now(self) -> datetime:
        """The current time, with its time zone."""
        ...
