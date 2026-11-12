"""
A local demonstration, not part of the service: sample orders, two signed tokens and the server, and a small client.

    just demo
    just call member get_order '{"order_id": "ORD-100001"}'
    just call customer_service cancel_order '{"order_id": "ORD-100005", "reason": "..."}'

The server writes the two tokens to a file in the system's temporary folder, so `call` takes a role name in place of
a token. A token pasted in its place works too. Without just, from the repository root:

    PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py
    PYTHONPATH=order_tools/src:. uv run python order_tools/demo.py call member get_order '{"order_id": "ORD-100001"}'
"""

import argparse
import asyncio
import json
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import TextContent

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.types.enums import OrderStatus, Role, SigningAlgorithm, TokenClaim
from b_application.config.app_config import AppConfig
from d_presentation.dependencies import build_pipeline, create_order_repository, open_database
from d_presentation.mcp_tools.server import build_server

ISSUER = "https://sso.example.com"
AUDIENCE = "order-tools"
HOST = "127.0.0.1"
PORT = 8000
TOKEN_LIFETIME_SECONDS = 3600
TOKEN_FILE = Path(tempfile.gettempdir()) / "order-tools-demo-tokens.json"
SUBJECTS = {Role.MEMBER: "member-001", Role.CUSTOMER_SERVICE: "cs-007"}

RECIPIENTS = {
    "member-001": Recipient(
        name="王小明", phone="0912-345-678", address="台北市大安區忠孝東路四段1號5樓", email="xiaoming.wang@example.com"
    ),
    "member-002": Recipient(name="陳美玲", phone="0987-654-321", address="新竹縣竹北市光明六路10號", email="meiling.chen@example.com"),
}
SAMPLE_ORDERS = [
    ("ORD-100001", "member-001", OrderStatus.PAID),
    ("ORD-100002", "member-001", OrderStatus.SHIPPED),
    ("ORD-100003", "member-001", OrderStatus.DELIVERED),
    ("ORD-100004", "member-001", OrderStatus.PENDING_PAYMENT),
    ("ORD-100005", "member-002", OrderStatus.PAID),
    ("ORD-100006", "member-002", OrderStatus.CANCELLED),
]


async def seed(order_repository: IOrderRepository) -> None:
    first_order_at = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    for hours, (order_id, owner_id, status) in enumerate(SAMPLE_ORDERS):
        created_at = first_order_at + timedelta(hours=hours)
        order = Order(
            id=order_id,
            owner_id=owner_id,
            status=OrderStatus.PAID if status == OrderStatus.CANCELLED else status,
            total_amount=1180,
            created_at=created_at,
        )

        if status == OrderStatus.CANCELLED:
            order.cancel(Role.MEMBER, "買錯尺寸", now=created_at + timedelta(minutes=5))

        await order_repository.add(order, RECIPIENTS[owner_id])


def sign_token(private_key: rsa.RSAPrivateKey, subject: str, role: Role, algorithm: SigningAlgorithm) -> str:
    issued_at = int(time.time())
    claims: dict[str, Any] = {
        TokenClaim.ISSUER: ISSUER,
        TokenClaim.AUDIENCE: AUDIENCE,
        TokenClaim.SUBJECT: subject,
        TokenClaim.ROLES: [role.value],
        TokenClaim.EXPIRES_AT: issued_at + TOKEN_LIFETIME_SECONDS,
        TokenClaim.TOKEN_ID: str(uuid.uuid4()),
    }

    return jwt.encode(claims, private_key, algorithm=algorithm)


def serve() -> None:
    folder = Path(tempfile.mkdtemp(prefix="order-tools-demo-"))
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_file = folder / "sso_public_key.pem"
    public_key_file.write_bytes(
        private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    config = AppConfig.model_validate(
        {
            "db": folder / "orders.db",
            "jwt_public_key": public_key_file,
            "jwt_issuer": ISSUER,
            "jwt_audience": AUDIENCE,
            "host": HOST,
            "port": PORT,
        }
    )
    database = asyncio.run(open_database(config))
    asyncio.run(seed(create_order_repository(database)))

    tokens = {role.value: sign_token(private_key, subject, role, config.jwt_algorithm) for role, subject in SUBJECTS.items()}
    TOKEN_FILE.write_text(json.dumps(tokens), encoding="utf-8")

    print(f"SQLite: {config.db}  (the audit_log table is the audit trail)")
    print(f"MCP endpoint: http://{config.host}:{config.port}/mcp")
    print(f"Signed in as: {', '.join(f'{role.value} ({subject})' for role, subject in SUBJECTS.items())}")
    print(f"Tokens: {TOKEN_FILE}\n", flush=True)
    build_server(build_pipeline(config, database), config).run(config.transport, host=config.host, port=config.port)


async def call(url: str, token: str, tool: str, arguments: dict[str, object]) -> None:
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http,
        Client(streamable_http_client(url, http_client=http)) as client,
    ):
        result = await client.call_tool(tool, arguments)

    if result.structured_content is not None:
        print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))
        return

    # An argument the input schema refuses is answered by the SDK itself, as text only.
    for block in result.content:
        if isinstance(block, TextContent):
            print(block.text)


def token_of(who: str) -> str:
    """The demo token of a role name, such as member. Anything else is taken as a token itself."""
    tokens = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else {}

    return tokens.get(who, who)


def leaf_errors(error: BaseException) -> list[BaseException]:
    """The MCP client raises its failures inside exception groups. These are the errors at the bottom."""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in leaf_errors(inner)]

    return [error]


def main() -> None:
    parser = argparse.ArgumentParser(prog="demo.py")
    commands = parser.add_subparsers(dest="command")
    call_parser = commands.add_parser("call", help="Call one tool as member or customer_service")
    call_parser.add_argument("who", help="member, customer_service, or a token")
    call_parser.add_argument("tool")
    call_parser.add_argument("arguments", nargs="?", default="{}")
    call_parser.add_argument("--url", default=f"http://{HOST}:{PORT}/mcp")
    arguments = parser.parse_args()

    if arguments.command != "call":
        serve()
        return

    try:
        asyncio.run(call(arguments.url, token_of(arguments.who), arguments.tool, json.loads(arguments.arguments)))
    except Exception as error:
        for leaf in leaf_errors(error):
            print(f"Call failed: {type(leaf).__name__}: {leaf}")

        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
