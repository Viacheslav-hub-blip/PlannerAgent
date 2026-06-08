"""Статическое ограничение набора tools, видимых конкретному агенту.

Содержит:
- ToolVisibilityMiddleware: фильтрация tools перед model call.
- filter_tools_by_name: выбор tools по разрешённым именам.
- filter_system_message_by_tools: удаление prompt-секций недоступных tools.
- _filter_tool_prompt_block: фильтрация одного системного prompt-блока.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

@dataclass(frozen=True)
class ToolVisibilityMiddleware(AgentMiddleware):
    """Оставляет модели только статически разрешённые инструменты.

    Args:
        allowed_tools: Имена tools, которые должны быть видимы модели.

    Returns:
        Middleware, фильтрующий список tools отдельно для своего agent stack.
    """

    allowed_tools: frozenset[str]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Фильтрует tools перед синхронным вызовом модели.

        Args:
            request: Запрос модели с полным набором tools.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели, полученный с разрешённым набором tools.
        """

        filtered_tools = filter_tools_by_name(request.tools, self.allowed_tools)
        system_message = filter_system_message_by_tools(
            request.system_message,
            self.allowed_tools,
        )
        return handler(request.override(tools=filtered_tools, system_message=system_message))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Фильтрует tools перед асинхронным вызовом модели.

        Args:
            request: Запрос модели с полным набором tools.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели, полученный с разрешённым набором tools.
        """

        filtered_tools = filter_tools_by_name(request.tools, self.allowed_tools)
        system_message = filter_system_message_by_tools(
            request.system_message,
            self.allowed_tools,
        )
        return await handler(
            request.override(tools=filtered_tools, system_message=system_message)
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Блокирует выполнение инструмента, отсутствующего в allowlist агента.

        Args:
            request: Запрос на выполнение tool.
            handler: Следующий обработчик tool call.

        Returns:
            Результат разрешённого tool либо компактная ошибка для скрытого tool.
        """

        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Асинхронно блокирует tool, отсутствующий в allowlist агента."""

        blocked = self._blocked_tool_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage | None:
        """Возвращает ошибку для скрытого tool или ``None`` для разрешённого.

        Args:
            request: Запрос на выполнение tool.

        Returns:
            ``ToolMessage`` с ошибкой либо ``None``.
        """

        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name") or "")
        if not tool_name or tool_name in self.allowed_tools:
            return None
        allowed = ", ".join(sorted(self.allowed_tools))
        return ToolMessage(
            content=(
                f"ToolUnavailableError: tool '{tool_name}' is not available to this agent. "
                f"Available tools: {allowed}"
            ),
            tool_call_id=str(tool_call.get("id") or ""),
            name=tool_name,
            status="error",
        )


def filter_tools_by_name(
    tools: list[BaseTool | dict[str, Any]],
    allowed_tools: frozenset[str],
) -> list[BaseTool | dict[str, Any]]:
    """Возвращает tools, имена которых присутствуют в allowlist.

    Args:
        tools: Полный список tools текущего model call.
        allowed_tools: Разрешённые имена инструментов.

    Returns:
        Новый список tools с сохранением исходного порядка.
    """

    return [
        tool
        for tool in tools
        if str(tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", ""))
        in allowed_tools
    ]


def filter_system_message_by_tools(
    system_message: SystemMessage | None,
    allowed_tools: frozenset[str],
) -> SystemMessage | None:
    """Удаляет встроенные prompt-блоки недоступных инструментов.

    Args:
        system_message: Системное сообщение, собранное DeepAgents.
        allowed_tools: Имена tools, реально доступных текущему агенту.

    Returns:
        Системное сообщение без секций, рекламирующих скрытые tools.
    """

    if system_message is None:
        return None

    filtered_blocks: list[dict[str, Any]] = []
    for block in system_message.content_blocks:
        if block.get("type") != "text":
            filtered_blocks.append(block)
            continue
        text = str(block.get("text") or "")
        replacement = _filter_tool_prompt_block(text, allowed_tools)
        if replacement.strip():
            filtered_blocks.append({"type": "text", "text": replacement})
    return SystemMessage(content=filtered_blocks)


def _filter_tool_prompt_block(text: str, allowed_tools: frozenset[str]) -> str:
    """Фильтрует один текстовый prompt-блок по allowlist.

    Args:
        text: Текст системного content block.
        allowed_tools: Имена доступных tools.

    Returns:
        Исходный, сокращённый или пустой текст.
    """

    if "## `write_todos`" in text and "write_todos" not in allowed_tools:
        return ""
    if "## `task` (subagent spawner)" in text and "task" not in allowed_tools:
        return ""
    if "## Execute Tool `execute`" in text and "execute" not in allowed_tools:
        return ""
    if "## Filesystem Tools `ls`, `read_file`" not in text:
        return text

    available_filesystem_tools = [
        name
        for name in ("ls", "read_file", "write_file", "edit_file", "glob", "grep")
        if name in allowed_tools
    ]
    if not available_filesystem_tools:
        return ""

    tools_list = ", ".join(f"`{name}`" for name in available_filesystem_tools)
    bullet_lines = "\n".join(
        f"- {name}: доступный filesystem tool; используй точную схему его аргументов."
        for name in available_filesystem_tools
    )
    return (
        "\n\n## Filesystem Tools\n\n"
        f"Текущему агенту доступны только: {tools_list}.\n"
        "Не вызывай и не упоминай другие filesystem tools.\n\n"
        f"{bullet_lines}"
    )


__all__ = [
    "ToolVisibilityMiddleware",
    "filter_system_message_by_tools",
    "filter_tools_by_name",
]
