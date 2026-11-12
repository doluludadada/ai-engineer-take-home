"""Signing in: the Pipeline's sign_in_with_token on tokens signed in the test, good and bad."""

import json
import time

import jwt
import pytest
from pydantic import ValidationError

from a_domain.types.enums import AuditAction, AuditOutcome, Role, SignInFailure
from a_domain.types.errors import TokenRefused
from b_application.config.app_config import AppConfig
from tests.q2.conftest import AUDIENCE, BOB, ISSUER


async def refused(pipeline, token: str) -> TokenRefused:
    with pytest.raises(TokenRefused) as refusal:
        await pipeline.sign_in_with_token(token)

    return refusal.value


async def test_valid_member_token_becomes_member_actor(pipeline, mint, audit_entries):
    actor = await pipeline.sign_in_with_token(mint("member-alice", jti="token-1"))

    assert (actor.subject, actor.role, actor.token_id) == ("member-alice", Role.MEMBER, "token-1")
    assert audit_entries() == []


async def test_valid_customer_service_token_becomes_customer_service_actor(pipeline, mint):
    actor = await pipeline.sign_in_with_token(mint("cs-agent-7", [Role.CUSTOMER_SERVICE.value]))

    assert actor.role is Role.CUSTOMER_SERVICE


async def test_expired_jwt_is_refused(pipeline, mint):
    an_hour_ago = int(time.time()) - 3600

    assert (await refused(pipeline, mint(exp=an_hour_ago, iat=an_hour_ago - 600))).detail == "ExpiredSignatureError"


async def test_bad_signature_jwt_is_refused(pipeline, mint, attacker_key):
    assert (await refused(pipeline, mint(key=attacker_key))).detail == "InvalidSignatureError"


async def test_tampered_payload_is_refused(pipeline, mint):
    header, _, signature = mint("member-alice").split(".")
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": BOB.subject, "roles": [Role.CUSTOMER_SERVICE.value], "exp": 9999999999}
    forged_payload = jwt.utils.base64url_encode(json.dumps(claims).encode()).decode()

    await refused(pipeline, f"{header}.{forged_payload}.{signature}")


async def test_wrong_audience_is_refused(pipeline, mint):
    await refused(pipeline, mint(aud="some-other-service"))


async def test_wrong_issuer_is_refused(pipeline, mint):
    await refused(pipeline, mint(iss="https://evil.example"))


async def test_unsigned_alg_none_token_is_refused(pipeline, mint):
    await refused(pipeline, mint(key="", algorithm="none"))


async def test_hs256_token_is_refused(pipeline, mint):
    await refused(pipeline, mint(key="a-shared-secret-that-is-long-enough-for-hs256", algorithm="HS256"))


@pytest.mark.parametrize("claim", ["sub", "roles", "exp", "aud", "iss"])
async def test_token_missing_a_required_claim_is_refused(pipeline, mint, claim):
    await refused(pipeline, mint(**{claim: None}))


@pytest.mark.parametrize(
    ("roles", "failure"),
    [
        ([], SignInFailure.NO_SINGLE_KNOWN_ROLE),
        (["warehouse"], SignInFailure.NO_SINGLE_KNOWN_ROLE),
        (["member", "customer_service"], SignInFailure.NO_SINGLE_KNOWN_ROLE),
        ("member", SignInFailure.INVALID_ROLES),
    ],
    ids=["empty", "unknown", "ambiguous", "not-a-list"],
)
async def test_token_without_exactly_one_known_role_is_refused(pipeline, mint, roles, failure):
    assert (await refused(pipeline, mint(roles=roles))).detail == failure


async def test_token_with_a_blank_subject_is_refused(pipeline, mint):
    assert (await refused(pipeline, mint("   "))).detail == SignInFailure.INVALID_SUBJECT


async def test_token_without_an_id_still_signs_in(pipeline, mint):
    assert (await pipeline.sign_in_with_token(mint(jti=None))).token_id is None


def test_settings_cannot_name_a_shared_secret_algorithm(config):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({**config.model_dump(), "jwt_algorithm": "HS256"})


async def test_refused_token_is_audited_without_the_token(pipeline, mint, attacker_key, audit_entries):
    forged = mint(key=attacker_key)

    await refused(pipeline, forged)

    [entry] = audit_entries()
    assert (entry.action, entry.outcome, entry.actor_subject, entry.detail) == (
        AuditAction.SIGN_IN,
        AuditOutcome.UNAUTHENTICATED,
        None,
        "InvalidSignatureError",
    )
    assert forged not in repr(entry)
