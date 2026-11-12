from pydantic.dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """Who receives an order: name, phone, address and email."""

    # All four fields are personal data, so an Order does not carry them: only the operation that answers with one
    # order loads its recipient, and it gets the masked values (RecipientMaskRule).

    name: str
    phone: str
    address: str
    email: str
