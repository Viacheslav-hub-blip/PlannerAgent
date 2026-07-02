"""Переопределение и фильтрация описаний инструментов перед вызовом модели.

Содержит:
- PromptToolDescriptionsMiddleware: middleware для замены tool descriptions.
- PromptToolFilterMiddleware: middleware для скрытия tools от модели.
- _rewrite_tool_descriptions: копирование tool metadata с новыми описаниями.
- _filter_tools_by_name: удаление tool metadata по имени инструмента.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class DiagnosticLoggingMiddleware(AgentMiddleware):
    """Печатает этапы вызова модели в stdout backend для первичной диагностики UI.

    Args:
        agent_name: Имя агента или subagent, для которого выполняется model call.

    Returns:
        Middleware, который не меняет запрос и ответ, а только пишет читаемые
        диагностические строки и traceback при ошибке.
    """

    agent_name: str

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Синхронно логирует старт, успех или ошибку model call.

        Args:
            request: Запрос к модели.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        started_at = time.perf_counter()
        _print_model_call_start(self.agent_name, request)
        try:
            response = handler(request)
        except Exception as error:
            _print_model_call_failure(self.agent_name, started_at, error)
            raise
        _print_model_call_success(self.agent_name, started_at, response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Асинхронно логирует старт, успех или ошибку model call.

        Args:
            request: Запрос к модели.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        started_at = time.perf_counter()
        _print_model_call_start(self.agent_name, request)
        try:
            response = await handler(request)
        except Exception as error:
            _print_model_call_failure(self.agent_name, started_at, error)
            raise
        _print_model_call_success(self.agent_name, started_at, response)
        return response


@dataclass(frozen=True)
class PromptToolDescriptionsMiddleware(AgentMiddleware):
    """Заменяет описания tools перед вызовом модели.

    Args:
        tool_descriptions: Новые описания tools, где ключ — имя инструмента.

    Returns:
        Middleware, который не меняет реализацию tools, а заменяет только descriptions,
        видимые модели.
    """

    tool_descriptions: Mapping[str, str]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Синхронно подменяет описания инструментов в запросе к модели.

        Args:
            request: Исходный запрос к модели с tools и system message.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели после вызова следующего обработчика.
        """

        return handler(self._override_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Асинхронно подменяет описания инструментов в запросе к модели.

        Args:
            request: Исходный запрос к модели с tools и system message.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели после вызова следующего обработчика.
        """

        return await handler(self._override_request(request))

    def _override_request(self, request: ModelRequest) -> ModelRequest:
        """Создаёт копию запроса с обновлёнными descriptions.

        Args:
            request: Исходный запрос к модели.

        Returns:
            Новый ``ModelRequest`` с prompt-only изменениями.
        """

        tools = _rewrite_tool_descriptions(request.tools, self.tool_descriptions)
        return request.override(tools=tools)


@dataclass(frozen=True)
class PromptToolFilterMiddleware(AgentMiddleware):
    """Скрывает указанные tools из запроса к модели.

    Args:
        hidden_tool_names: Имена инструментов, которые нужно убрать из списка tools
            перед model call.

    Returns:
        Middleware, который фильтрует metadata инструментов, видимых модели, без
        изменения backend и других агентов.
    """

    hidden_tool_names: tuple[str, ...]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Синхронно удаляет скрытые инструменты из запроса к модели.

        Args:
            request: Исходный запрос к модели с tools.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели после вызова следующего обработчика.
        """

        return handler(self._override_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Асинхронно удаляет скрытые инструменты из запроса к модели.

        Args:
            request: Исходный запрос к модели с tools.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели после вызова следующего обработчика.
        """

        return await handler(self._override_request(request))

    def _override_request(self, request: ModelRequest) -> ModelRequest:
        """Создаёт копию запроса без скрытых tools.

        Args:
            request: Исходный запрос к модели.

        Returns:
            Новый ``ModelRequest`` без tools из ``hidden_tool_names``.
        """

        tools = _filter_tools_by_name(request.tools, self.hidden_tool_names)
        return request.override(tools=tools)


def _rewrite_tool_descriptions(
    tools: list[BaseTool | dict[str, Any]],
    descriptions: Mapping[str, str],
) -> list[BaseTool | dict[str, Any]]:
    """Возвращает копию списка tools с переопределёнными descriptions.

    Args:
        tools: Инструменты, которые будут переданы модели.
        descriptions: Новые описания по имени инструмента.

    Returns:
        Новый список tools; сами функции инструментов не изменяются.
    """

    rewritten: list[BaseTool | dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        description = descriptions.get(str(name)) if name else None
        if description is None:
            rewritten.append(tool)
            continue
        if isinstance(tool, dict):
            copied = dict(tool)
            copied["description"] = description
            rewritten.append(copied)
        else:
            rewritten.append(tool.model_copy(update={"description": description}))
    return rewritten


def _filter_tools_by_name(
    tools: list[BaseTool | dict[str, Any]],
    hidden_tool_names: tuple[str, ...],
) -> list[BaseTool | dict[str, Any]]:
    """Возвращает список tools без инструментов с указанными именами.

    Args:
        tools: Инструменты, которые будут переданы модели.
        hidden_tool_names: Имена инструментов, которые нужно скрыть.

    Returns:
        Новый список tools без элементов, имя которых входит в ``hidden_tool_names``.
    """

    hidden_names = set(hidden_tool_names)
    return [
        tool
        for tool in tools
        if (tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None))
        not in hidden_names
    ]


def _diagnostic_timestamp() -> str:
    """Возвращает timestamp для диагностических строк backend.

    Returns:
        Строка времени с точностью до секунд.
    """

    return datetime.now().isoformat(timespec="seconds")


def _tool_name(tool: BaseTool | dict[str, Any]) -> str:
    """Возвращает имя инструмента из dict или LangChain ``BaseTool``.

    Args:
        tool: Описание инструмента, переданное модели.

    Returns:
        Имя инструмента или ``unknown``.
    """

    name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
    return str(name or "unknown")


def _print_model_call_start(agent_name: str, request: ModelRequest) -> None:
    """Печатает строку старта model call.

    Args:
        agent_name: Имя агента.
        request: Запрос к модели.

    Returns:
        ``None``.
    """

    messages = getattr(request, "messages", []) or []
    tools = getattr(request, "tools", []) or []
    tool_names = [_tool_name(tool) for tool in tools]
    print(
        f"[{_diagnostic_timestamp()}] [model-call] START "
        f"agent={agent_name} messages={len(messages)} tools={len(tools)} "
        f"tool_names={tool_names}",
        flush=True,
    )


def _print_model_call_success(
    agent_name: str,
    started_at: float,
    response: ModelResponse,
) -> None:
    """Печатает строку успешного завершения model call.

    Args:
        agent_name: Имя агента.
        started_at: Время старта из ``time.perf_counter``.
        response: Ответ модели.

    Returns:
        ``None``.
    """

    elapsed = time.perf_counter() - started_at
    result = getattr(response, "result", response)
    content = getattr(result, "content", "")
    tool_calls = getattr(result, "tool_calls", []) or []
    content_chars = len(content) if isinstance(content, str) else len(str(content))
    print(
        f"[{_diagnostic_timestamp()}] [model-call] SUCCESS "
        f"agent={agent_name} elapsed_sec={elapsed:.2f} "
        f"response_type={type(response).__name__} content_chars={content_chars} "
        f"tool_calls={len(tool_calls)}",
        flush=True,
    )


def _print_model_call_failure(
    agent_name: str,
    started_at: float,
    error: Exception,
) -> None:
    """Печатает строку ошибки model call и полный traceback.

    Args:
        agent_name: Имя агента.
        started_at: Время старта из ``time.perf_counter``.
        error: Исключение, возникшее при вызове модели.

    Returns:
        ``None``.
    """

    elapsed = time.perf_counter() - started_at
    print(
        f"[{_diagnostic_timestamp()}] [model-call] FAILED "
        f"agent={agent_name} elapsed_sec={elapsed:.2f} "
        f"error={type(error).__name__}: {error}",
        flush=True,
    )
    print(traceback.format_exc(), flush=True)


__all__ = [
    "DiagnosticLoggingMiddleware",
    "PromptToolDescriptionsMiddleware",
    "PromptToolFilterMiddleware",
]
