from typing import Annotated

from pydantic import Field

type OrderId = Annotated[str, Field(pattern=r"^ORD-[0-9]{6}$")]
"""An order number as the shop prints it: ORD- and six digits. The tools publish this pattern as their input schema."""

type UserId = Annotated[str, Field(pattern=r"\S")]
"""A member or a person in customer service: the `sub` of their SSO token. An order's owner and an actor are compared by it."""
