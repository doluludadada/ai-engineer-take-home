"""Fixtures for the order tool server: a signed-token maker, a seeded SQLite file and the real Pipeline on it."""

import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.model.system.actor import Actor
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.types.enums import OrderStatus, Role
from b_application.config.app_config import AppConfig
from b_application.pipeline import Pipeline
from c_infrastructure.database.db_connector import DatabaseConnector
from d_presentation.dependencies import build_pipeline, create_order_repository, open_database

ISSUER = "https://sso.test.example"
AUDIENCE = "order-tools"


@dataclass(frozen=True)
class Customer:
    subject: str
    recipient: Recipient


ALICE = Customer(
    "member-alice",
    Recipient(name="王小明", phone="0912-345-678", address="台北市大安區忠孝東路四段1號5樓", email="xiaoming.wang@example.com"),
)
BOB = Customer(
    "member-bob", Recipient(name="陳美玲", phone="0987-654-321", address="新竹縣竹北市光明六路10號", email="meiling.chen@example.com")
)


@dataclass(frozen=True)
class World:
    """The seeded orders by what they are for, and one actor of each kind."""

    alice: Customer
    bob: Customer
    alice_pending: str
    alice_paid: str
    alice_shipped: str
    alice_delivered: str
    bob_paid: str
    missing: str
    member_alice: Actor
    member_bob: Actor
    customer_service: Actor


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def attacker_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def config(signing_key: rsa.RSAPrivateKey, tmp_path: Path) -> AppConfig:
    public_key_file = tmp_path / "sso_public_key.pem"
    public_key_file.write_bytes(
        signing_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )

    return AppConfig(db=tmp_path / "orders.db", jwt_public_key=public_key_file, jwt_issuer=ISSUER, jwt_audience=AUDIENCE)


@pytest.fixture
def mint(signing_key: rsa.RSAPrivateKey, config: AppConfig) -> Callable[..., str]:
    """Signs a token with the algorithm the settings name. Passing None for a claim leaves that claim out."""

    def sign(
        subject: Any = ALICE.subject,
        roles: Any = (Role.MEMBER.value,),
        *,
        key: Any = None,
        algorithm: str | None = None,
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "roles": list(roles) if isinstance(roles, tuple) else roles,
            "iat": now,
            "exp": now + 600,
            "jti": str(uuid.uuid4()),
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}

        return jwt.encode(claims, key if key is not None else signing_key, algorithm=algorithm or config.jwt_algorithm)

    return sign


@pytest.fixture
async def database(config: AppConfig) -> DatabaseConnector:
    return await open_database(config)


@pytest.fixture
def order_repository(database: DatabaseConnector) -> IOrderRepository:
    return create_order_repository(database)


@pytest.fixture
def audit_entries(config: AppConfig, database: DatabaseConnector) -> Callable[[], list[SimpleNamespace]]:
    """Reads the audit_log table straight from the SQLite file, oldest first, one object per row with its columns."""

    def read() -> list[SimpleNamespace]:
        with closing(sqlite3.connect(config.db)) as connection:
            connection.row_factory = sqlite3.Row
            return [SimpleNamespace(**dict(row)) for row in connection.execute("SELECT * FROM audit_log ORDER BY id")]

    return read


@pytest.fixture
def pipeline(config: AppConfig, database: DatabaseConnector) -> Pipeline:
    return build_pipeline(config, database)


@pytest.fixture
async def world(order_repository: IOrderRepository) -> World:
    first_order_at = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    seeded = [
        ("ORD-000001", ALICE, OrderStatus.PENDING_PAYMENT),
        ("ORD-000002", ALICE, OrderStatus.PAID),
        ("ORD-000003", ALICE, OrderStatus.SHIPPED),
        ("ORD-000004", ALICE, OrderStatus.DELIVERED),
        ("ORD-000005", BOB, OrderStatus.PAID),
    ]

    for hours, (order_id, owner, status) in enumerate(seeded):
        await order_repository.add(
            Order(
                id=order_id,
                owner_id=owner.subject,
                status=status,
                total_amount=1180,
                created_at=first_order_at + timedelta(hours=hours),
            ),
            owner.recipient,
        )

    return World(
        alice=ALICE,
        bob=BOB,
        alice_pending="ORD-000001",
        alice_paid="ORD-000002",
        alice_shipped="ORD-000003",
        alice_delivered="ORD-000004",
        bob_paid="ORD-000005",
        missing="ORD-999999",
        member_alice=Actor(subject=ALICE.subject, role=Role.MEMBER, token_id="jti-alice"),
        member_bob=Actor(subject=BOB.subject, role=Role.MEMBER, token_id="jti-bob"),
        customer_service=Actor(subject="cs-agent-7", role=Role.CUSTOMER_SERVICE, token_id="jti-agent"),
    )
