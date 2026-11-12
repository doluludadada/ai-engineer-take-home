"""Mask customer PII before a request leaves for a cloud model, and restore it after."""

import copy
import re
from collections.abc import Iterator, Sequence
from itertools import count
from typing import Any, override

from pii_guard.detectors import DEFAULT_PROTECTED, EntityKind, find_pii

__all__ = ["DEFAULT_PROTECTED", "EntityKind", "StreamUnmasker", "Vault", "mask", "mask_messages", "unmask"]

_PLACEHOLDER = re.compile(r"\[(?:" + "|".join(EntityKind) + r")_\d+\]")


class Vault:
    """The placeholder table for one conversation. It lives in local memory only."""

    def __init__(self) -> None:
        self._placeholder_by_value: dict[str, str] = {}
        self._value_by_placeholder: dict[str, str] = {}
        self._last_number = dict.fromkeys(EntityKind, 0)
        self._reserved: set[str] = set()

    @override
    def __repr__(self) -> str:
        return f"Vault(<{len(self._value_by_placeholder)} entries hidden>)"

    def reserve_literals(self, text: str) -> None:
        """Remembers every placeholder-shaped string the text already holds, so no value is ever given that placeholder."""
        self._reserved.update(_PLACEHOLDER.findall(text))

    def placeholder_for(self, kind: EntityKind, value: str) -> str:
        """The value's placeholder: the one it already has in this conversation, or the next free number of its kind."""
        if value in self._placeholder_by_value:
            return self._placeholder_by_value[value]
        number = next(candidate for candidate in count(self._last_number[kind] + 1) if f"[{kind}_{candidate}]" not in self._reserved)
        self._last_number[kind] = number
        placeholder = f"[{kind}_{number}]"
        self._placeholder_by_value[value] = placeholder
        self._value_by_placeholder[placeholder] = value
        return placeholder

    def value_for(self, placeholder: str) -> str:
        """The value a placeholder stands for. A placeholder this vault never issued comes back as it is."""
        return self._value_by_placeholder.get(placeholder, placeholder)


def mask(text: str, vault: Vault, protected: Sequence[re.Pattern[str]] = DEFAULT_PROTECTED) -> str:
    vault.reserve_literals(text)
    pieces, cursor = [], 0
    for kind, start, end in find_pii(text, protected):
        pieces += [text[cursor:start], vault.placeholder_for(kind, text[start:end])]
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def unmask(text: str, vault: Vault) -> str:
    return _PLACEHOLDER.sub(lambda match: vault.value_for(match.group()), text)


def _text_slots(messages: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], str]]:
    """
    Yield (container, key) for the text this module masks: string content, the text parts of list content, and the
    arguments of function tool calls, in the current `tool_calls` shape and the older `function_call` one. A tool call
    of any other shape raises KeyError, so the gateway blocks the request instead of sending text nobody checked.
    """
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            yield message, "content"
        elif isinstance(content, list):
            yield from ((part, "text") for part in content if part.get("type") == "text")
        if message.get("function_call"):
            yield message["function_call"], "arguments"
        for call in message.get("tool_calls") or ():
            yield call["function"], "arguments"


def mask_messages(
    messages: list[dict[str, Any]], vault: Vault, protected: Sequence[re.Pattern[str]] = DEFAULT_PROTECTED
) -> list[dict[str, Any]]:
    masked = copy.deepcopy(messages)
    slots = list(_text_slots(masked))
    # Reserve every literal placeholder first, so a value in an early message
    # cannot take a number that a later message already uses as plain text.
    for container, key in slots:
        vault.reserve_literals(container[key])
    for container, key in slots:
        container[key] = mask(container[key], vault, protected)
    return masked


def _could_become_placeholder(tail: str) -> bool:
    body = tail[1:]
    for kind in EntityKind:
        head = f"{kind}_"
        if head.startswith(body) or (body.startswith(head) and body[len(head) :].isdigit()):
            return True
    return False


class StreamUnmasker:
    """Restore placeholders in a streamed reply, holding back a tail that may be half a placeholder."""

    def __init__(self, vault: Vault) -> None:
        self._vault = vault
        self._pending = ""

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        cut = self._pending.rfind("[")
        if cut == -1 or not _could_become_placeholder(self._pending[cut:]):
            cut = len(self._pending)
        ready, self._pending = self._pending[:cut], self._pending[cut:]
        return unmask(ready, self._vault)

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        return unmask(ready, self._vault)
