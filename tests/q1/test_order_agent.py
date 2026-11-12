import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion
from pydantic import ValidationError

from q1_review.order_agent import FALLBACK_REPLY, CancelOutcome, OrderRepository, Settings, run

ALICE = "u-alice"
SETTINGS = Settings(gateway_url="http://gateway.test/v1", gateway_api_key="test-key", model_alias="chat-cheap", timeout_seconds=5)


def tool_call_reply(name: str, arguments: str, call_id: str = "call_1") -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "r",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}],
                    },
                }
            ],
        }
    )


def text_reply(text: str) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "r",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        }
    )


class FakeGateway:
    """Replies from a script and records every request sent to the gateway. Once the script runs out, the last reply repeats."""

    def __init__(self, *replies: ChatCompletion) -> None:
        self._replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]

    def tool_result_sent_back(self, request_index: int = 1) -> dict:
        last = self.requests[request_index]["messages"][-1]
        assert last["role"] == "tool"
        return json.loads(last["content"])


@pytest.fixture
def connection():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE orders (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, status TEXT NOT NULL,"
        " total_amount INTEGER NOT NULL, created_at TEXT NOT NULL, phone TEXT, address TEXT)"
    )
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("A1001", "u-alice", "paid", 1200, "2026-11-01", "0912345678", "台北市信義區松仁路 100 號"),
            ("A1002", "u-bob", "paid", 800, "2026-11-02", "0987654321", "新北市板橋區文化路 1 號"),
            ("A1003", "u-alice", "shipped", 450, "2026-10-20", "0912345678", "台北市信義區松仁路 100 號"),
        ],
    )
    connection.commit()
    yield connection
    connection.close()


def statuses(connection) -> dict[str, str]:
    return dict(connection.execute("SELECT id, status FROM orders").fetchall())


def ask(connection, gateway: FakeGateway, user_id: str = ALICE) -> str:
    return run("help", user_id=user_id, client=gateway, repository=OrderRepository(connection), settings=SETTINGS)


def test_member_cannot_read_another_members_order(connection):
    gateway = FakeGateway(tool_call_reply("get_order", '{"order_id": "A1002"}'), text_reply("查不到"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["error"] == "NOT_FOUND"


def test_member_cannot_cancel_another_members_order(connection):
    gateway = FakeGateway(tool_call_reply("cancel_order", '{"order_id": "A1002"}'), text_reply("無法取消"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["error"] == "NOT_FOUND"
    assert statuses(connection)["A1002"] == "paid"


def test_own_order_reaches_model_without_phone_or_address(connection):
    gateway = FakeGateway(tool_call_reply("get_order", '{"order_id": "A1001"}'), text_reply("已付款"))
    ask(connection, gateway)
    sent = gateway.requests[1]["messages"][-1]["content"]
    assert json.loads(sent)["status"] == "paid"
    assert "0912345678" not in sent
    assert "松仁路" not in sent


def test_injection_payload_from_model_cancels_nothing(connection):
    payload = json.dumps({"order_id": "X' OR '1'='1"})
    gateway = FakeGateway(tool_call_reply("cancel_order", payload), text_reply("格式錯誤"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["error"] == "INVALID_ARGUMENTS"
    assert statuses(connection) == {"A1001": "paid", "A1002": "paid", "A1003": "shipped"}


def test_repository_treats_injection_payload_as_a_plain_value(connection):
    repository = OrderRepository(connection)
    assert repository.find_for_owner("A1001' OR '1'='1", "u-alice") is None
    assert repository.cancel_for_owner("X' OR '1'='1", "u-alice") is None
    assert statuses(connection) == {"A1001": "paid", "A1002": "paid", "A1003": "shipped"}


def test_model_cannot_call_functions_outside_the_registry(connection):
    gateway = FakeGateway(tool_call_reply("run", '{"user_message": "loop"}'), text_reply("ok"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["error"] == "UNKNOWN_TOOL"
    assert len(gateway.requests) == 2


def test_malformed_tool_arguments_are_reported_to_the_model(connection):
    gateway = FakeGateway(tool_call_reply("get_order", '{"order_id": "A1001"'), text_reply("請再說一次"))
    assert ask(connection, gateway) == "請再說一次"
    assert gateway.tool_result_sent_back()["error"] == "INVALID_ARGUMENTS"


def test_tool_result_follows_the_assistant_message_that_requested_it(connection):
    gateway = FakeGateway(tool_call_reply("get_order", '{"order_id": "A1001"}', call_id="call_42"), text_reply("ok"))
    ask(connection, gateway)
    assistant, tool = gateway.requests[1]["messages"][-2:]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "call_42"
    assert (tool["role"], tool["tool_call_id"]) == ("tool", "call_42")


def test_loop_gives_up_after_max_steps(connection):
    gateway = FakeGateway(tool_call_reply("get_order", '{"order_id": "A1001"}'))
    assert ask(connection, gateway) == FALLBACK_REPLY
    assert len(gateway.requests) == SETTINGS.max_steps


def test_tool_call_on_the_last_step_is_not_run(connection):
    lookups = [tool_call_reply("get_order", '{"order_id": "A1001"}')] * (SETTINGS.max_steps - 1)
    gateway = FakeGateway(*lookups, tool_call_reply("cancel_order", '{"order_id": "A1001"}'))
    assert ask(connection, gateway) == FALLBACK_REPLY
    assert statuses(connection)["A1001"] == "paid"


def test_member_cancels_own_paid_order(connection):
    gateway = FakeGateway(tool_call_reply("cancel_order", '{"order_id": "A1001"}'), text_reply("已取消"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["outcome"] == CancelOutcome.CANCELLED
    assert statuses(connection)["A1001"] == "cancelled"


def test_shipped_order_is_not_cancelled(connection):
    gateway = FakeGateway(tool_call_reply("cancel_order", '{"order_id": "A1003"}'), text_reply("已出貨"))
    ask(connection, gateway)
    assert gateway.tool_result_sent_back()["outcome"] == CancelOutcome.NOT_CANCELLABLE
    assert statuses(connection)["A1003"] == "shipped"


def test_repeated_cancel_reports_already_cancelled(connection):
    repository = OrderRepository(connection)
    assert repository.cancel_for_owner("A1001", "u-alice") == CancelOutcome.CANCELLED
    assert repository.cancel_for_owner("A1001", "u-alice") == CancelOutcome.ALREADY_CANCELLED


def test_requests_use_the_configured_gateway_alias(connection):
    gateway = FakeGateway(text_reply("hi"))
    ask(connection, gateway)
    assert gateway.requests[0]["model"] == "chat-cheap"


def test_settings_come_from_the_environment_not_the_source(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.test/v1")
    monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings.model_validate({})

    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "k")
    settings = Settings.model_validate({})
    assert (settings.gateway_api_key.get_secret_value(), settings.model_alias) == ("k", "chat-default")
    assert "k" not in repr(settings.gateway_api_key)
