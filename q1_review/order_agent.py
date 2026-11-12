"""The order assistant, fixed.

It shows the fix for the three most important problems of the question 1 review. REVIEW.md lists the rest.
1. No identity and no authorization: the member comes from the SSO identity the HTTP layer verified, and every query
   carries an owner_id condition.
2. SQL injection: every query takes its values as parameters.
3. Any function could be called: the tools are a registry, and their arguments are validated.
The same loop also gets the assistant message it was missing and a step limit, and a tool error now goes back to the
model instead of failing the whole request.

Nothing tunable is written in the code. settings.json beside this file holds the model alias, the timeout, the retry
and step limits, the order number format and every sentence the model or the customer reads. The gateway address and
the key come from the environment, as LLM_GATEWAY_URL and LLM_GATEWAY_API_KEY. LLM_MODEL_ALIAS, LLM_TIMEOUT_SECONDS,
LLM_MAX_RETRIES and LLM_MAX_STEPS override the file for one deployment.
"""

import json
import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionAssistantMessageParam, ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = json.loads((Path(__file__).parent / "settings.json").read_text(encoding="utf-8"))
TEXTS: dict[str, Any] = DEFAULTS["texts"]
SYSTEM_PROMPT: str = TEXTS["system_prompt"]
FALLBACK_REPLY: str = TEXTS["fallback_reply"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    gateway_url: str
    gateway_api_key: SecretStr
    """This agent's own key. It comes from the environment only, so it is in no file and in no repr."""

    model_alias: str = DEFAULTS["model_alias"]
    """An alias the gateway defines, such as chat-default. A provider's model name bypasses the gateway's routing."""

    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = DEFAULTS["timeout_seconds"]
    max_retries: Annotated[int, Field(ge=0, le=5)] = DEFAULTS["max_retries"]
    max_steps: Annotated[int, Field(ge=2, le=20)] = DEFAULTS["max_steps"]
    """
    How many times one request may call the model. A conversation that never settles stops here. At least two: one
    call to ask for a tool and one to read its result.
    """


def make_client(settings: Settings) -> OpenAI:
    return OpenAI(
        base_url=settings.gateway_url,
        api_key=settings.gateway_api_key.get_secret_value(),
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ToolName(StrEnum):
    """The tools the model may call. Anything else it names is refused."""

    GET_ORDER = "get_order"
    CANCEL_ORDER = "cancel_order"


class ToolError(StrEnum):
    """The error codes a tool result carries back to the model."""

    NOT_FOUND = "NOT_FOUND"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    TOOL_FAILED = "TOOL_FAILED"


class CancelOutcome(StrEnum):
    CANCELLED = "cancelled"
    ALREADY_CANCELLED = "already_cancelled"
    NOT_CANCELLABLE = "not_cancellable"


class OrderRepository:
    """
    Every query names the owner, so a member reaches only their own orders, and it selects only the columns the model
    needs: phone, address and other personal data never leave this class.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def find_for_owner(self, order_id: str, owner_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT id, status, total_amount, created_at FROM orders WHERE id = ? AND owner_id = ?", (order_id, owner_id)
        ).fetchone()

        if row is None:
            return None

        return {"order_id": row[0], "status": row[1], "total_amount": row[2], "created_at": row[3]}

    def cancel_for_owner(self, order_id: str, owner_id: str) -> CancelOutcome | None:
        """Cancels the owner's order if it has not shipped. None when the owner has no such order."""
        with self._connection:
            updated = self._connection.execute(
                "UPDATE orders SET status = ? WHERE id = ? AND owner_id = ? AND status IN (?, ?)",
                (OrderStatus.CANCELLED, order_id, owner_id, OrderStatus.PENDING_PAYMENT, OrderStatus.PAID),
            ).rowcount

        if updated == 1:
            return CancelOutcome.CANCELLED

        order = self.find_for_owner(order_id, owner_id)

        if order is None:
            return None

        if order["status"] == OrderStatus.CANCELLED:
            return CancelOutcome.ALREADY_CANCELLED

        return CancelOutcome.NOT_CANCELLABLE


class OrderIdArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(pattern=DEFAULTS["order_id_pattern"], description=TEXTS["order_id"])


@dataclass(frozen=True)
class Tool:
    description: str
    arguments: type[BaseModel]
    function: Callable[[Any], dict[str, Any]]


def build_tools(repository: OrderRepository, user_id: str) -> dict[str, Tool]:
    """The registry: the only functions the model can reach, each bound to the signed-in member."""
    not_found = {"error": ToolError.NOT_FOUND, "message": TEXTS["not_found"]}

    def get_order(arguments: OrderIdArguments) -> dict[str, Any]:
        return repository.find_for_owner(arguments.order_id, user_id) or not_found

    def cancel_order(arguments: OrderIdArguments) -> dict[str, Any]:
        outcome = repository.cancel_for_owner(arguments.order_id, user_id)

        if outcome is None:
            return not_found

        return {"order_id": arguments.order_id, "outcome": outcome, "message": TEXTS["cancel_messages"][outcome]}

    return {
        ToolName.GET_ORDER: Tool(TEXTS["tools"][ToolName.GET_ORDER], OrderIdArguments, get_order),
        ToolName.CANCEL_ORDER: Tool(TEXTS["tools"][ToolName.CANCEL_ORDER], OrderIdArguments, cancel_order),
    }


def tool_specifications(tools: Mapping[str, Tool]) -> list[ChatCompletionToolParam]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": tool.description, "parameters": tool.arguments.model_json_schema()},
        }
        for name, tool in tools.items()
    ]


def execute_tool_call(tools: Mapping[str, Tool], name: str, raw_arguments: str) -> dict[str, Any]:
    tool = tools.get(name)

    if tool is None:
        return {"error": ToolError.UNKNOWN_TOOL, "message": TEXTS["unknown_tool"].format(name=name)}

    try:
        arguments = tool.arguments.model_validate_json(raw_arguments)
    except ValidationError as error:
        problems = [problem["msg"] for problem in error.errors()]
        return {"error": ToolError.INVALID_ARGUMENTS, "message": TEXTS["invalid_arguments"], "details": problems}

    try:
        return tool.function(arguments)
    except Exception:
        log.exception("tool %s failed", name)
        return {"error": ToolError.TOOL_FAILED, "message": TEXTS["tool_failed"]}


def run(user_message: str, *, user_id: str, client: OpenAI, repository: OrderRepository, settings: Settings) -> str:
    """
    Answers one message from a member. `user_id` is the member the HTTP layer read from a verified SSO token, and
    nothing the model outputs can change it.
    """
    tools = build_tools(repository, user_id)
    specifications = tool_specifications(tools)
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    for step in range(settings.max_steps):
        response = client.chat.completions.create(model=settings.model_alias, messages=messages, tools=specifications)
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content or FALLBACK_REPLY

        if step == settings.max_steps - 1:
            # No call is left to read a result, so this step's tool calls are not run.
            break

        messages.append(cast(ChatCompletionAssistantMessageParam, message.model_dump(exclude_none=True)))

        for call in message.tool_calls:
            name, raw_arguments = (call.function.name, call.function.arguments) if call.type == "function" else (call.type, "")
            result = execute_tool_call(tools, name, raw_arguments)
            log.info("tool=%s user=%s error=%s", name, user_id, result.get("error"))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

    log.warning("agent stopped after %d steps for user %s", settings.max_steps, user_id)

    return FALLBACK_REPLY
