"""Middleware добавления понятных уведомлений к результатам tools.

Содержит:
- ToolContextNoticeMiddleware: middleware с текстовым notice о передаче контекста.
- build_tool_context_notice: формирование notice для конкретного инструмента.
- build_tool_error_recovery_hint: формирование подсказки для неуспешного tool call.
- is_tool_error_content: эвристика определения текстовой ошибки tool.
- _tool_name_from_request: извлечение имени tool из запроса.
- _tool_call_id_from_request: извлечение id tool call из запроса.
- _tool_exception_message: преобразование exception в ToolMessage.
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

TOOL_ERROR_RECOVERY_HINT = (
    "Попробуйте вызвать инструмент с другими параметрами или использовать другой инструмент."
)


@dataclass(frozen=True)
class ToolContextNoticeMiddleware(AgentMiddleware):
    """Добавляет уведомления к успешным и неуспешным результатам tool.

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

        try:
            result = handler(request)
        except Exception as exc:  # noqa: BLE001
            return _tool_exception_message(request, exc)
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

        try:
            result = await handler(request)
        except Exception as exc:  # noqa: BLE001
            return _tool_exception_message(request, exc)
        if not self.enabled or not isinstance(result, ToolMessage):
            return result
        return self._with_notice(result, _tool_name_from_request(request))

    def _with_notice(self, result: ToolMessage, tool_name: str) -> ToolMessage:
        """Возвращает ToolMessage с notice или подсказкой для ошибки.

        Args:
            result: Результат tool call.
            tool_name: Имя вызванного инструмента.

        Returns:
            ToolMessage с исходным content, notice или подсказкой восстановления.
        """

        if not isinstance(result.content, str):
            return result
        if result.status == "error" or is_tool_error_content(result.content):
            return _copy_tool_message_with_content(
                result,
                _append_error_recovery_hint(result.content),
            )
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


def build_tool_error_recovery_hint() -> str:
    """Возвращает подсказку для восстановления после ошибки tool.

    Returns:
        Русский текст рекомендации для агента после неуспешного вызова инструмента.
    """

    return TOOL_ERROR_RECOVERY_HINT


def is_tool_error_content(content: str) -> bool:
    """Определяет, похож ли текстовый результат tool на ошибку.

    Args:
        content: Текстовый content из ``ToolMessage``.

    Returns:
        ``True``, если content начинается с известного error-префикса.
    """

    stripped = str(content or "").lstrip()
    error_prefixes = (
        "Error:",
        "Exception:",
        "ToolUnavailableError:",
        "ImageAnalysisError:",
        "ValueError:",
        "TypeError:",
        "FileNotFoundError:",
        "PermissionError:",
        "RuntimeError:",
        "SyntaxError:",
        "ImportError:",
        "ModuleNotFoundError:",
    )
    return stripped.startswith(error_prefixes)


def _append_error_recovery_hint(content: str) -> str:
    """Добавляет подсказку восстановления к тексту ошибки, если её ещё нет.

    Args:
        content: Исходный текст ошибки.

    Returns:
        Текст ошибки с рекомендацией повторного вызова или смены инструмента.
    """

    hint = build_tool_error_recovery_hint()
    if hint in content:
        return content
    return f"{content.rstrip()}\n\n{hint}"


def _tool_name_from_request(request: ToolCallRequest) -> str:
    """Извлекает имя tool из запроса LangChain.

    Args:
        request: Запрос tool call.

    Returns:
        Имя инструмента или ``tool``.
    """

    tool_call = request.tool_call or {}
    return str(tool_call.get("name") or "tool")


def _tool_call_id_from_request(request: ToolCallRequest) -> str:
    """Извлекает id tool call из запроса LangChain.

    Args:
        request: Запрос tool call.

    Returns:
        Идентификатор tool call или пустую строку.
    """

    tool_call = request.tool_call or {}
    return str(tool_call.get("id") or "")


def _tool_exception_message(request: ToolCallRequest, error: Exception) -> ToolMessage:
    """Преобразует исключение tool handler в ToolMessage для возврата агенту.

    Args:
        request: Запрос tool call.
        error: Исключение, выброшенное инструментом или backend.

    Returns:
        ``ToolMessage`` со статусом ``error`` и подсказкой восстановления.
    """

    message = str(error).strip()
    content = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return ToolMessage(
        content=_append_error_recovery_hint(content),
        tool_call_id=_tool_call_id_from_request(request),
        name=_tool_name_from_request(request),
        status="error",
    )


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


__all__ = [
    "ToolContextNoticeMiddleware",
    "build_tool_context_notice",
    "build_tool_error_recovery_hint",
    "is_tool_error_content",
]
