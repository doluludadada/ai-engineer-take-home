from pydantic.dataclasses import dataclass

from a_domain.types.enums import Role
from a_domain.types.ids import UserId


@dataclass(frozen=True, kw_only=True)
class Actor:
    """
    The person operating, as their verified SSO token says. It is built only from a verified token and never from a
    tool argument: the model fills the arguments, and whoever writes to the model could name anyone there.
    """

    subject: UserId
    """The token's `sub`: the member, or the person in customer service."""

    role: Role

    token_id: str | None = None
    """The token's `jti`. The audit log keeps it in place of the token."""
