from typing import Protocol

from pydantic.dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class VerifiedToken:
    """What a token says once its signature, expiry, audience and issuer are checked."""

    subject: str
    roles: tuple[str, ...]
    token_id: str | None


class ITokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedToken:
        """Raises TokenRefused for a token that is expired, forged, malformed, or meant for another service or issuer."""
        ...
