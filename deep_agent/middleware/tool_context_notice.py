"""Middleware добавления понятных уведомлений к результатам tools.

Содержит:
- ToolContextNoticeMiddleware: middleware с текстовым notice о передаче контекста.
- build_tool_context_notice: формирование notice для конкретного инструмента.
- _tool_name_from_request: извлечение имени tool из запроса.
- _copy_tool_message_with_content: копирование ToolMessage с новым content.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


@dataclass(frozen=True)
class ToolContextNoticeMiddleware(AgentMiddleware):
    """Добавляет к успешному текстовому результату tool короткое уведомление.

    Args:
        enabled: Включено ли добавление notice к результатам инструментов.
    """

    enabled: bool = True

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Выполняет синхронный tool call и добавляет notice к ToolMessage.

        Args:
            request: Запрос tool call.
            handler: Следующий обработчик tool call.

        Returns:
            Исходный результат или ToolMessage с добавленным notice.
        """

        result = handler(request)
        if not self.enabled or not isinstance(result, ToolMessage):
            return result
        return self._with_notice(result, _tool_name_from_request(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Асинхронно выполняет tool call и добавляет notice к ToolMessage.

        Args:
            request: Запрос tool call.
            handler: Следующий асинхронный обработчик tool call.

        Returns:
            Исходный результат или ToolMessage с добавленным notice.
        """

        result = await handler(request)
        if not self.enabled or not isinstance(result, ToolMessage):
            return result
        return self._with_notice(result, _tool_name_from_request(request))

    def _with_notice(self, result: ToolMessage, tool_name: str) -> ToolMessage:
        """Возвращает ToolMessage с notice, если результат успешный и текстовый.

        Args:
            result: Результат tool call.
            tool_name: Имя вызванного инструмента.

        Returns:
            ToolMessage с исходным content или content с notice.
        """

        if result.status == "error" or not isinstance(result.content, str):
            return result
        notice = build_tool_context_notice(tool_name)
        if not notice or result.content.startswith(notice):
            return result
        return _copy_tool_message_with_content(result, f"{notice}\n\n{result.content}")


def build_tool_context_notice(tool_name: str) -> str:
    """Формирует человекочитаемое уведомление для результата tool.

    Args:
        tool_name: Имя инструмента.

    Returns:
        Короткий notice о том, какой контекст был получен.
    """

    notices = {
        "read_file": "Файл прочитан, текстовый контекст получен и передан агенту.",
        "grep": "Поиск выполнен, найденный текстовый контекст передан агенту.",
        "glob": "Поиск файлов выполнен, список найденных путей передан агенту.",
        "ls": "Содержимое директории получено и передано агенту.",
        "load_data": "Данные загружены, результат запроса передан агенту.",
        "execute_python_code": "Python-код выполнен, результат вычисления передан агенту.",
        "execute": "Команда выполнена, вывод терминала передан агенту.",
        "analyze_image": "Изображение проанализировано, визуальный контекст передан агенту.",
    }
    return notices.get(
        tool_name,
        f"Инструмент `{tool_name}` выполнен, результат передан агенту.",
    )


def _tool_name_from_request(request: ToolCallRequest) -> str:
    """Извлекает имя tool из запроса LangChain.

    Args:
        request: Запрос tool call.

    Returns:
        Имя инструмента или ``tool``.
    """

    tool_call = request.tool_call or {}
    return str(tool_call.get("name") or "tool")


def _copy_tool_message_with_content(
    message: ToolMessage,
    content: str,
) -> ToolMessage:
    """Копирует ToolMessage, заменяя только content.

    Args:
        message: Исходный результат инструмента.
        content: Новый текстовый content.

    Returns:
        Новый ToolMessage с сохранением metadata исходного сообщения.
    """

    return ToolMessage(
        content=content,
        artifact=message.artifact,
        tool_call_id=message.tool_call_id,
        name=message.name,
        status=message.status,
        additional_kwargs=message.additional_kwargs,
        response_metadata=message.response_metadata,
        id=message.id,
    )


__all__ = ["ToolContextNoticeMiddleware", "build_tool_context_notice"]
