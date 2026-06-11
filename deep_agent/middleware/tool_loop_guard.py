"""Middleware защиты от циклов идентичных tool calls.

Содержит:
- ToolLoopGuardMiddleware: блокировка серии идентичных вызовов.
- _count_trailing_identical_tool_calls: подсчёт серии по имени и аргументам.
- _tool_call_signature: построение канонической сигнатуры вызова.
- _normalize_tool_value: нормализация вложенных аргументов.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deep_agent.state import extract_state_messages


@dataclass(frozen=True)
class ToolLoopGuardMiddleware(AgentMiddleware):
    """Блокирует вызов tool после N подряд идущих идентичных вызовов.

    Args:
        max_consecutive_tool_calls: Сколько идентичных вызовов подряд разрешено.
            Изменение нормализованных аргументов начинает новую серию.
        exclude_tools: Имена инструментов, к которым guard не применяется.
    """

    max_consecutive_tool_calls: int = 4
    exclude_tools: frozenset[str] = frozenset()

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Синхронно проверяет длину серии повторов перед выполнением tool."""

        blocked = self._loop_block_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Асинхронно проверяет длину серии повторов перед выполнением tool."""

        blocked = self._loop_block_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)

    def _loop_block_message(self, request: ToolCallRequest) -> ToolMessage | None:
        """Возвращает блокирующий ToolMessage, если серия повторов исчерпана, иначе None."""

        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name") or "")
        if not tool_name or tool_name in self.exclude_tools:
            return None

        # Текущий AIMessage уже находится в state к моменту wrap_tool_call.
        consecutive_count = _count_trailing_identical_tool_calls(
            request.state,
            tool_call,
        )
        if consecutive_count <= self.max_consecutive_tool_calls:
            return None

        payload = {
            "error_category": "technical_loop",
            "failing_input": {
                "tool": tool_name,
                "args": _normalize_tool_value(tool_call.get("args") or {}),
            },
            "expected": (
                "Изменённые аргументы, новый подтверждённый источник контекста "
                "или завершение шага по уже полученным данным."
            ),
            "observed": (
                f"{consecutive_count} идентичных вызовов подряд при разрешённом "
                f"максимуме {self.max_consecutive_tool_calls}."
            ),
            "retryable": False,
            "correction_hint": (
                "Не повторяй тот же вызов. Исправь аргументы по фактической ошибке, "
                "загрузи дополнительный подтверждённый context другим вызовом или заверши шаг."
            ),
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            tool_call_id=str(tool_call.get("id") or ""),
            name=tool_name,
            status="error",
        )


def _count_trailing_identical_tool_calls(
    state: Any,
    current_tool_call: dict[str, Any],
) -> int:
    """Считает серию идентичных вызовов до текущего tool call включительно.

    Args:
        state: State агента с историей сообщений.
        current_tool_call: Текущий вызов с ``id``, ``name`` и ``args``.

    Returns:
        Число подряд идущих вызовов с той же канонической сигнатурой.
    """

    messages = extract_state_messages(state)
    calls: list[dict[str, Any] | None] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            calls.append(None)
            continue
        if not isinstance(message, AIMessage):
            continue
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            calls.append(None)
            continue
        calls.extend(tool_call for tool_call in tool_calls if isinstance(tool_call, dict))

    current_id = str(current_tool_call.get("id") or "")
    current_index = -1
    if current_id:
        for index in range(len(calls) - 1, -1, -1):
            if calls[index] is not None and str(calls[index].get("id") or "") == current_id:
                current_index = index
                break
    if current_index < 0:
        calls.append(current_tool_call)
        current_index = len(calls) - 1

    signature = _tool_call_signature(current_tool_call)
    count = 0
    for tool_call in reversed(calls[: current_index + 1]):
        if tool_call is None:
            break
        if _tool_call_signature(tool_call) != signature:
            break
        count += 1
    return count


def _tool_call_signature(tool_call: dict[str, Any]) -> tuple[str, str]:
    """Строит каноническую сигнатуру tool call.

    Args:
        tool_call: Вызов инструмента с именем и аргументами.

    Returns:
        Кортеж из имени tool и JSON нормализованных аргументов.
    """

    tool_name = str(tool_call.get("name") or "")
    normalized_args = _normalize_tool_value(tool_call.get("args") or {})
    return tool_name, json.dumps(
        normalized_args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _normalize_tool_value(value: Any) -> Any:
    """Нормализует вложенное значение аргументов для сравнения.

    Args:
        value: Скаляр, mapping или последовательность из tool args.

    Returns:
        JSON-совместимое значение со стабильным порядком ключей и пробелов.
    """

    if isinstance(value, dict):
        return {
            str(key): _normalize_tool_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_tool_value(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


__all__ = [
    "ToolLoopGuardMiddleware",
    "_count_trailing_identical_tool_calls",
    "_tool_call_signature",
]
