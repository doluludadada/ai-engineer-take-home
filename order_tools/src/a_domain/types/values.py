from typing import Annotated

from pydantic import Field

type NonEmptyText = Annotated[str, Field(pattern=r"\S")]

type ListLimit = Annotated[int, Field(ge=1, le=50)]
"""How many orders one listing returns at most."""

type CancelReason = Annotated[str, Field(max_length=200)]
"""Why an order is cancelled, as the actor wrote it. An empty text means no reason was given."""
