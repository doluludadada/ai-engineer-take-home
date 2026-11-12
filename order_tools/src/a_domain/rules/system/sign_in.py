from collections.abc import Sequence

from pydantic.dataclasses import dataclass

from a_domain.model.system.actor import Actor
from a_domain.types.enums import Role, SignInFailure
from a_domain.types.errors import TokenRefused


@dataclass(frozen=True)
class ActorRule:
    """
    Who a verified token stands for. Its `roles` claim must name exactly one role this service knows. A token with
    none, or with both member and customer service, is refused: the service never guesses which one the person acts as.
    """

    def apply(self, subject: str, roles: Sequence[str], token_id: str | None) -> Actor:
        known = {Role(role) for role in roles if role in Role}

        if len(known) != 1:
            raise TokenRefused(SignInFailure.NO_SINGLE_KNOWN_ROLE)

        return Actor(subject=subject, role=known.pop(), token_id=token_id)
