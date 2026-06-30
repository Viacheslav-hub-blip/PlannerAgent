"""Middleware единого контракта путей для filesystem tools.

Содержит:
- FilesystemPathContractMiddleware: нормализация путей и проверка записи файлов.
- normalize_filesystem_tool_path: приведение tool-пути к POSIX-виду от корня workspace.
- _normalize_filesystem_tool_call: нормализация аргументов filesystem tool call.
- _verify_file_write: проверка, что файл доступен после ``write_file`` или ``edit_file``.
- _file_path_arg_name: имя аргумента пути для filesystem tool.
- _tool_message_with_content: копирование ``ToolMessage`` с новым содержимым.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deep_agent.agent_settings import strip_workspace_tool_prefix, workspace_tool_path

WRITE_TOOLS = {"write_file", "edit_file"}
MAX_EXACT_WRITE_VERIFY_CHARS = 100_000
MAX_EXACT_WRITE_VERIFY_LINES = 10_000


@dataclass(frozen=True)
class FilesystemPathContractMiddleware(AgentMiddleware):
    """Нормализует пути filesystem tools и проверяет успешные записи.

    Args:
        workspace_root: Фактический корень workspace текущего запуска.
        backend: Backend DeepAgents, через который выполняется проверочное чтение.
        enabled: Включена ли нормализация и проверка.

    Returns:
        Middleware, который передает tool handler только canonical POSIX-пути вида
        ``/path/from/workspace`` и превращает неподтвержденную запись в error-result.
    """

    workspace_root: Path
    backend: Any
    enabled: bool = True

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Выполняет tool call с нормализованными путями и проверкой записи.

        Args:
            request: Запрос tool call от модели.
            handler: Следующий обработчик tool call.

        Returns:
            Результат tool call. Для неподдерживаемого или некорректного пути
            возвращается ``ToolMessage`` со статусом ``error``.
        """

        if not self.enabled:
            return handler(request)
        normalized_request = _normalize_filesystem_tool_call(
            request,
            workspace_root=self.workspace_root,
        )
        if isinstance(normalized_request, ToolMessage):
            return normalized_request

        result = handler(normalized_request)
        if isinstance(result, ToolMessage):
            return self._verify_write_result(normalized_request, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Асинхронно выполняет tool call с нормализованными путями и проверкой записи.

        Args:
            request: Запрос tool call от модели.
            handler: Следующий асинхронный обработчик tool call.

        Returns:
            Результат tool call. Для неподдерживаемого или некорректного пути
            возвращается ``ToolMessage`` со статусом ``error``.
        """

        if not self.enabled:
            return await handler(request)
        normalized_request = _normalize_filesystem_tool_call(
            request,
            workspace_root=self.workspace_root,
        )
        if isinstance(normalized_request, ToolMessage):
            return normalized_request

        result = await handler(normalized_request)
        if isinstance(result, ToolMessage):
            return self._verify_write_result(normalized_request, result)
        return result

    def _verify_write_result(
        self,
        request: ToolCallRequest,
        result: ToolMessage,
    ) -> ToolMessage:
        """Проверяет успешный результат ``write_file`` или ``edit_file``.

        Args:
            request: Нормализованный запрос tool call.
            result: Результат, полученный от filesystem tool.

        Returns:
            Исходный результат с добавленным подтверждением или error-result, если
            файл нельзя прочитать после записи.
        """

        tool_name = _tool_name_from_request(request)
        if tool_name not in WRITE_TOOLS or result.status == "error":
            return result
        verification = _verify_file_write(request, self.backend)
        if verification["status"] == "error":
            return _tool_message_with_content(
                result,
                str(verification["message"]),
                status="error",
            )
        return _tool_message_with_content(
            result,
            f"{result.content.rstrip()}\n\n{verification['message']}",
        )


def normalize_filesystem_tool_path(value: str, workspace_root: Path) -> str:
    """Приводит путь filesystem tool к canonical POSIX-виду от ``/``.

    Args:
        value: Путь из аргументов tool call.
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        Абсолютный POSIX-путь вида ``/artifacts/file.md``.

    Raises:
        ValueError: Путь пустой или абсолютный OS-путь указывает вне workspace.
    """

    raw_path = str(value or "").strip()
    if not raw_path:
        raise ValueError("Путь filesystem tool не может быть пустым.")

    normalized = raw_path.replace("\\", "/")
    relative_path = strip_workspace_tool_prefix(normalized, workspace_root)
    if relative_path is not None:
        return "/" if not relative_path else f"/{relative_path}"

    candidate = Path(raw_path)
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
        try:
            resolved.relative_to(workspace_root.resolve())
        except ValueError:
            raise ValueError(
                "Filesystem tool принимает только POSIX-пути внутри workspace "
                f"вида `/path`: {raw_path}"
            ) from None
        return workspace_tool_path(resolved, workspace_root.resolve())

    normalized_relative = normalized.lstrip("/")
    if not normalized_relative:
        return "/"
    return f"/{normalized_relative}"


def _normalize_filesystem_tool_call(
    request: ToolCallRequest,
    *,
    workspace_root: Path,
) -> ToolCallRequest | ToolMessage:
    """Нормализует аргумент пути в filesystem tool call.

    Args:
        request: Исходный запрос tool call.
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        Новый ``ToolCallRequest`` с canonical-путем или ``ToolMessage`` со
        статусом ``error`` при некорректном пути.
    """

    tool_name = _tool_name_from_request(request)
    path_arg = _file_path_arg_name(tool_name)
    if path_arg is None:
        return request

    args = dict((request.tool_call or {}).get("args") or {})
    if path_arg not in args:
        return request
    try:
        args[path_arg] = normalize_filesystem_tool_path(
            str(args[path_arg]),
            workspace_root.resolve(),
        )
    except ValueError as error:
        return ToolMessage(
            content=f"ValueError: {error}",
            tool_call_id=_tool_call_id_from_request(request),
            name=tool_name,
            status="error",
        )

    tool_call = dict(request.tool_call or {})
    tool_call["args"] = args
    return request.override(tool_call=tool_call)


def _verify_file_write(request: ToolCallRequest, backend: Any) -> dict[str, str]:
    """Проверяет доступность файла после успешного write/edit tool call.

    Args:
        request: Нормализованный запрос ``write_file`` или ``edit_file``.
        backend: Backend DeepAgents с методом ``read``.

    Returns:
        Словарь со статусом ``success`` или ``error`` и сообщением для модели.
    """

    tool_name = _tool_name_from_request(request)
    args = dict((request.tool_call or {}).get("args") or {})
    file_path = str(args.get("file_path") or "")
    read = getattr(backend, "read", None)
    if not callable(read):
        return {
            "status": "error",
            "message": (
                "FilesystemVerificationError: backend не поддерживает "
                f"проверочное чтение файла `{file_path}`."
            ),
        }

    read_result = read(file_path, offset=0, limit=MAX_EXACT_WRITE_VERIFY_LINES)
    if getattr(read_result, "error", None):
        return {
            "status": "error",
            "message": (
                "FilesystemVerificationError: файл не подтвержден после записи "
                f"`{file_path}`: {read_result.error}"
            ),
        }
    file_data = getattr(read_result, "file_data", None)
    if not file_data or "content" not in file_data:
        return {
            "status": "error",
            "message": (
                "FilesystemVerificationError: файл не подтвержден после записи "
                f"`{file_path}`: содержимое не получено."
            ),
        }

    if tool_name == "write_file":
        expected_content = str(args.get("content") or "")
        actual_content = str(file_data.get("content") or "")
        expected_line_count = len(expected_content.splitlines())
        can_compare_exactly = (
            len(expected_content) <= MAX_EXACT_WRITE_VERIFY_CHARS
            and expected_line_count <= MAX_EXACT_WRITE_VERIFY_LINES
        )
        if can_compare_exactly and actual_content != expected_content:
            return {
                "status": "error",
                "message": (
                    "FilesystemVerificationError: файл записан, но проверочное "
                    f"чтение `{file_path}` вернуло другое содержимое."
                ),
            }

    return {
        "status": "success",
        "message": f"FilesystemVerification: файл `{file_path}` прочитан после записи; сохранение подтверждено.",
    }


def _file_path_arg_name(tool_name: str) -> str | None:
    """Возвращает имя path-аргумента для filesystem tool.

    Args:
        tool_name: Имя инструмента.

    Returns:
        ``file_path`` для файловых tools, ``path`` для directory/search tools
        или ``None`` для не-filesystem tool.
    """

    if tool_name in {"read_file", "write_file", "edit_file"}:
        return "file_path"
    if tool_name in {"ls", "glob", "grep"}:
        return "path"
    return None


def _tool_name_from_request(request: ToolCallRequest) -> str:
    """Извлекает имя tool из запроса.

    Args:
        request: Запрос tool call.

    Returns:
        Имя инструмента или ``tool``.
    """

    tool_call = request.tool_call or {}
    return str(tool_call.get("name") or "tool")


def _tool_call_id_from_request(request: ToolCallRequest) -> str:
    """Извлекает id tool call из запроса.

    Args:
        request: Запрос tool call.

    Returns:
        Идентификатор tool call или пустую строку.
    """

    tool_call = request.tool_call or {}
    return str(tool_call.get("id") or "")


def _tool_message_with_content(
    message: ToolMessage,
    content: str,
    *,
    status: str | None = None,
) -> ToolMessage:
    """Копирует ``ToolMessage`` с новым содержимым и статусом.

    Args:
        message: Исходный результат tool call.
        content: Новый текст результата.
        status: Новый статус или ``None`` для сохранения исходного.

    Returns:
        Новый ``ToolMessage`` с сохранением metadata исходного сообщения.
    """

    return ToolMessage(
        content=content,
        artifact=message.artifact,
        tool_call_id=message.tool_call_id,
        name=message.name,
        status=status or message.status,
        additional_kwargs=message.additional_kwargs,
        response_metadata=message.response_metadata,
        id=message.id,
    )


__all__ = [
    "FilesystemPathContractMiddleware",
    "normalize_filesystem_tool_path",
]
