import re
from typing import Annotated

from pydantic import BaseModel, Field

from a_domain.types.values import NonEmptyText


class MaskingConfig(BaseModel):
    """How a recipient's personal data is masked before a tool answers with it."""

    mask_character: Annotated[str, Field(min_length=1, max_length=1)]
    """What replaces one hidden character of a name or one hidden digit of a phone number."""

    hidden_text: NonEmptyText
    """What replaces a value that is hidden whole, and the hidden part of an email address."""

    phone_visible_digits: Annotated[int, Field(ge=0, le=4)]
    """How many digits stay readable at the end of a phone number."""

    address_area_pattern: re.Pattern[str]
    """
    A regular expression matched at the start of an address. What its groups capture, joined, is all that stays
    readable: the city and the district.
    """
