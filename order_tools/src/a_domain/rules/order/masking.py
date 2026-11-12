import re
from dataclasses import replace
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.order.recipient import Recipient
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True)
class RecipientMaskRule:
    """
    The recipient as a tool may answer with it: enough for the model to confirm which order this is, and too little to
    reach or find the person. Whatever a tool answers stays in the model provider's, the agent's and the gateway's logs.

    - name: the first and last characters, with the rest masked. A two-character name keeps only its first.
    - phone: the last `phone_visible_digits` digits. Separators stay, so the number keeps its shape.
    - address: what the groups of `address_area_pattern` find at its start, such as the city and the district.
    - email: the first character and the domain, when the value is one address and nothing more.
    An address, an email or a phone that cannot be read this way is replaced whole by `hidden_text`.
    """

    mask_character: Annotated[str, Field(min_length=1, max_length=1)]
    hidden_text: NonEmptyText
    phone_visible_digits: Annotated[int, Field(ge=0)]
    address_area_pattern: re.Pattern[str]

    def apply(self, recipient: Recipient) -> Recipient:
        return replace(
            recipient,
            name=self._name(recipient.name),
            phone=self._phone(recipient.phone),
            address=self._address(recipient.address),
            email=self._email(recipient.email),
        )

    def _name(self, name: str) -> str:
        if len(name) <= 1:
            return self.mask_character

        if len(name) == 2:
            return name[0] + self.mask_character

        return name[0] + self.mask_character * (len(name) - 2) + name[-1]

    def _phone(self, phone: str) -> str:
        digits_to_hide = sum(character.isdigit() for character in phone) - self.phone_visible_digits

        if digits_to_hide <= 0 or any(character.isalpha() for character in phone):
            return self.hidden_text

        masked = []

        for character in phone:
            if character.isdigit() and digits_to_hide > 0:
                digits_to_hide -= 1
                masked.append(self.mask_character)
            else:
                masked.append(character)

        return "".join(masked)

    def _address(self, address: str) -> str:
        area = self.address_area_pattern.match(address)

        if area is None:
            return self.hidden_text

        return "".join(area.groups(default="")) or self.hidden_text

    def _email(self, email: str) -> str:
        local, at, domain = email.partition("@")

        if not (local and at and domain.isascii() and domain.replace(".", "").replace("-", "").isalnum()):
            return self.hidden_text

        return f"{local[0]}{self.hidden_text}{at}{domain}"
