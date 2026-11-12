from typing import override

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from a_domain.ports.system.token_verifier import ITokenVerifier, VerifiedToken
from a_domain.types.enums import SignInFailure, TokenClaim
from a_domain.types.errors import TokenRefused
from b_application.config.app_config import AppConfig


class JwtTokenVerifier(ITokenVerifier):
    """
    Checks a token against the company SSO's public key. It accepts only the algorithm the settings name, which
    SigningAlgorithm limits to asymmetric ones: that refuses an unsigned token (alg=none) and a token signed with the
    public key as an HMAC secret (HS256). A refusal carries the name of the failure, such as ExpiredSignatureError, and
    never the token or any claim from it.
    """

    def __init__(self, public_key: RSAPublicKey, config: AppConfig) -> None:
        self._public_key = public_key
        self._algorithm = config.jwt_algorithm
        self._issuer = config.jwt_issuer
        self._audience = config.jwt_audience
        self._leeway_seconds = config.jwt_leeway_seconds

    @override
    def verify(self, token: str) -> VerifiedToken:
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={"require": [claim for claim in TokenClaim if claim.required]},
            )
        except jwt.InvalidTokenError as error:
            raise TokenRefused(type(error).__name__) from error

        subject, roles, token_id = claims[TokenClaim.SUBJECT], claims[TokenClaim.ROLES], claims.get(TokenClaim.TOKEN_ID)

        if not subject.strip():
            raise TokenRefused(SignInFailure.INVALID_SUBJECT)

        if not isinstance(roles, list):
            raise TokenRefused(SignInFailure.INVALID_ROLES)

        return VerifiedToken(subject=subject, roles=tuple(role for role in roles if isinstance(role, str)), token_id=token_id)
