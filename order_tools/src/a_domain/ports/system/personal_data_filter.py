from typing import Protocol


class IPersonalDataFilter(Protocol):
    def remove(self, text: str) -> str:
        """
        The text with every Taiwanese mobile number, email address, national ID and card number in it replaced by a
        placeholder. A name, an address, a landline or a foreign phone number stays.
        """
        ...
