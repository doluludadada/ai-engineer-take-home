import asyncio
import json
from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import AnyHttpUrl, Field

from a_domain.model.system.actor import Actor
from a_domain.types.errors import OrderNotCancellable, Refusal, TokenRefused
from a_domain.types.ids import OrderId
from a_domain.types.values import CancelReason, ListLimit
from b_application.config.app_config import AppConfig
from b_application.config.texts_config import TextsConfig
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.dependencies import build_pipeline, load_config, open_database
from d_presentation.mcp_tools.schemas import CancellationResponse, OrderListResponse, OrderResponse


class ActorAccessToken(AccessToken):
    """The SDK's access token with the actor the Pipeline made of it, so each tool reads the actor and never a claim."""

    actor: Actor


class SsoTokenVerifier:
    """
    The SDK's TokenVerifier. It runs on every HTTP request, before any tool. A refused token returns None, and the
    SDK answers 401 without running a tool.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            actor = await self._pipeline.sign_in_with_token(token)
        except TokenRefused:
            return None

        # The SDK ties an MCP session to its client and subject. An SSO token has no OAuth client, so the subject stands
        # in for it, and another person's token cannot take over the session.
        return ActorAccessToken(token=token, client_id=actor.subject, scopes=[], subject=actor.subject, actor=actor)


def current_actor() -> Actor | None:
    """The actor of this request's verified token. None when the server runs without the HTTP bearer check."""
    access_token = get_access_token()

    return access_token.actor if isinstance(access_token, ActorAccessToken) else None


def request_id(context: Context, config: AppConfig) -> str:
    """The gateway's request id when its header is there. A JSON-RPC id is unique only inside one MCP session."""
    return ((context.headers or {}).get(config.request_id_header) or context.request_id)[: config.request_id_max_length]


def refusal_text(refusal: Refusal, texts: TextsConfig) -> str:
    """The sentence the model reads for a refusal: the one for the order's status when the settings hold one."""
    if isinstance(refusal, OrderNotCancellable) and refusal.status in texts.not_cancellable:
        return texts.not_cancellable[refusal.status]

    return texts.refusals[refusal.outcome]


async def answer(
    operation: Awaitable[PipelineStatus], response: type[OrderResponse | OrderListResponse | CancellationResponse], texts: TextsConfig
) -> CallToolResult:
    """
    Runs one Pipeline operation and turns it into a tool result. A refusal becomes isError with a code the agent can
    branch on and a sentence for the model to read.

    The operation runs behind a shield, as its own task. A client may stop waiting for its call, but an operation that
    started always runs to its end and records its real outcome: a cancel that landed in the middle of the guarded
    UPDATE would otherwise leave SQLite's write lock with a dropped connection.
    """
    payload: dict[str, Any]

    try:
        payload = response.from_status(await asyncio.shield(operation)).model_dump(mode="json")
        refused = False
    except Refusal as refusal:
        payload = {"error": {"code": refusal.outcome.error_code, "message": refusal_text(refusal, texts)}}
        refused = True

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))], structured_content=payload, is_error=refused
    )


def add_get_order(server: MCPServer, pipeline: Pipeline, config: AppConfig) -> None:
    texts = config.texts

    @server.tool(description=texts.get_order_description, annotations=ToolAnnotations(read_only_hint=True))
    async def get_order(
        order_id: Annotated[OrderId, Field(description=texts.order_id_argument)], context: Context
    ) -> Annotated[CallToolResult, OrderResponse]:
        return await answer(pipeline.get_order(current_actor(), order_id, request_id(context, config)), OrderResponse, texts)


def add_list_my_orders(server: MCPServer, pipeline: Pipeline, config: AppConfig) -> None:
    texts = config.texts

    @server.tool(description=texts.list_my_orders_description, annotations=ToolAnnotations(read_only_hint=True))
    async def list_my_orders(
        context: Context, limit: Annotated[ListLimit, Field(description=texts.limit_argument)] = config.list_default_limit
    ) -> Annotated[CallToolResult, OrderListResponse]:
        return await answer(pipeline.list_my_orders(current_actor(), limit, request_id(context, config)), OrderListResponse, texts)


def add_cancel_order(server: MCPServer, pipeline: Pipeline, config: AppConfig) -> None:
    texts = config.texts

    @server.tool(
        description=texts.cancel_order_description,
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True),
    )
    async def cancel_order(
        order_id: Annotated[OrderId, Field(description=texts.order_id_argument)],
        context: Context,
        reason: Annotated[CancelReason, Field(description=texts.reason_argument)] = "",
    ) -> Annotated[CallToolResult, CancellationResponse]:
        operation = pipeline.cancel_order(current_actor(), order_id, reason, request_id(context, config))

        return await answer(operation, CancellationResponse, texts)


def build_server(pipeline: Pipeline, config: AppConfig) -> MCPServer:
    """
    The three tools on one MCP server. No tool has a user id argument: the model fills the arguments, so an identity
    there would be whatever the user, or a page the model read, told it to write.
    """
    server = MCPServer(
        name=config.server_name,
        instructions=config.texts.server_instructions,
        token_verifier=SsoTokenVerifier(pipeline),
        auth=AuthSettings(issuer_url=AnyHttpUrl(config.jwt_issuer), resource_server_url=None),
    )
    add_get_order(server, pipeline, config)
    add_list_my_orders(server, pipeline, config)
    add_cancel_order(server, pipeline, config)

    return server


def main() -> None:
    config = load_config()
    database = asyncio.run(open_database(config))
    build_server(build_pipeline(config, database), config).run(config.transport, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
