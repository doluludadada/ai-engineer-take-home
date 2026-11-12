import asyncio

from a_domain.model.system.actor import Actor
from a_domain.model.system.audit_entry import AuditEntry
from a_domain.ports.system.audit_log import IAuditLog
from a_domain.ports.system.clock import IClock
from a_domain.ports.system.token_verifier import ITokenVerifier
from a_domain.rules.system.sign_in import ActorRule
from a_domain.types.enums import AuditAction
from a_domain.types.errors import TokenRefused


class SignIn:
    """
    Use Case: Turn the SSO token a request carries into the actor. A refused token is written to the audit log with
    the kind of failure and without the token, and the refusal is raised again for the caller to answer. A token that
    passes leaves no entry of its own: the operation it then starts leaves one.
    """

    def __init__(self, token_verifier: ITokenVerifier, audit_log: IAuditLog, clock: IClock) -> None:
        self._token_verifier = token_verifier
        self._audit_log = audit_log
        self._clock = clock
        self._actor_rule = ActorRule()

    async def execute(self, token: str) -> Actor:
        try:
            verified = self._token_verifier.verify(token)
            return self._actor_rule.apply(verified.subject, verified.roles, verified.token_id)
        except TokenRefused as refusal:
            entry = AuditEntry(
                occurred_at=self._clock.now(),
                actor=None,
                action=AuditAction.SIGN_IN,
                order_id=None,
                outcome=refusal.outcome,
                detail=refusal.detail,
            )
            await asyncio.shield(self._audit_log.record(entry))
            raise
