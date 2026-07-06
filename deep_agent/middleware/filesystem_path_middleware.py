"""Middleware единого контракта путей для filesystem tools.

Содержит:
- FilesystemPathContractMiddleware: нормализация путей filesystem tools.
- normalize_filesystem_tool_path: приведение tool-пути к POSIX-виду от корня workspace.
- _normalize_filesystem_tool_call: нормализация аргументов filesystem tool call.
- _file_path_arg_name: имя аргумента пути для filesystem tool.
- _append_file_operation_preview: добавление проверки и preview после записи файла.
- _build_file_operation_preview: сборка JSON-проверки созданного или измененного файла.
- _resolve_workspace_local_path: преобразование canonical tool-пути в реальный путь workspace.
- _read_text_preview: чтение первых строк текстового файла.
- _copy_tool_message_with_content: копирование ToolMessage с новым content.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deep_agent.agent_settings import strip_workspace_tool_prefix, workspace_tool_path

@dataclass(frozen=True)
class FilesystemPathContractMiddleware(AgentMiddleware):
    """Нормализует пути filesystem tools.

    Args:
        workspace_root: Фактический корень workspace текущего запуска.
        backend: Backend DeepAgents, сохраненный для совместимости конфигурации.
        enabled: Включена ли нормализация.

    Returns:
        Middleware, который передает tool handler только canonical POSIX-пути вида
        ``/path/from/workspace``.
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
        """Добавляет к успешной записи проверку существования файла и preview.

        Args:
            request: Нормализованный запрос tool call.
            result: Результат, полученный от filesystem tool.

        Returns:
            ToolMessage с исходным результатом и проверочным блоком для записи.
        """

        return _append_file_operation_preview(
            request,
            result,
            workspace_root=self.workspace_root,
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


def _append_file_operation_preview(
    request: ToolCallRequest,
    result: ToolMessage,
    *,
    workspace_root: Path,
) -> ToolMessage:
    """Добавляет к результату файловой записи JSON с проверкой и preview.

    Args:
        request: Нормализованный запрос tool call.
        result: Результат filesystem tool.
        workspace_root: Реальный корень workspace текущего запуска.

    Returns:
        Исходный ToolMessage или копия с добавленным блоком ``file_operation_verification``.
    """

    tool_name = _tool_name_from_request(request)
    if tool_name not in {"write_file", "edit_file"}:
        return result
    if result.status == "error" or not isinstance(result.content, str):
        return result

    args = dict((request.tool_call or {}).get("args") or {})
    file_path = str(args.get("file_path") or "").strip()
    if not file_path:
        return result

    verification = _build_file_operation_preview(
        tool_name=tool_name,
        file_path=file_path,
        workspace_root=workspace_root,
        preview_lines=30,
    )
    content = result.content.rstrip()
    appended = (
        f"{content}\n\nfile_operation_verification:\n"
        f"{json.dumps(verification, ensure_ascii=False, indent=2)}"
    )
    return _copy_tool_message_with_content(result, appended)


def _build_file_operation_preview(
    *,
    tool_name: str,
    file_path: str,
    workspace_root: Path,
    preview_lines: int,
) -> dict[str, Any]:
    """Собирает проверочную информацию по файлу после ``write_file`` или ``edit_file``.

    Args:
        tool_name: Имя файлового инструмента.
        file_path: Canonical tool-путь файла внутри workspace.
        workspace_root: Реальный корень workspace.
        preview_lines: Максимальное число строк preview.

    Returns:
        Словарь с фактом существования, размером, абсолютным путем и preview.
    """

    try:
        local_path = _resolve_workspace_local_path(file_path, workspace_root)
    except ValueError as error:
        return {
            "tool": tool_name,
            "file_path": file_path,
            "verified": False,
            "error": f"ValueError: {error}",
        }

    exists = local_path.is_file()
    preview = _read_text_preview(local_path, max_lines=preview_lines) if exists else {
        "available": False,
        "error": "Файл не найден после выполнения tool.",
        "lines": [],
    }
    return {
        "tool": tool_name,
        "file_path": file_path,
        "absolute_path": str(local_path),
        "verified": exists,
        "size_bytes": local_path.stat().st_size if exists else 0,
        "preview": preview,
    }


def _resolve_workspace_local_path(file_path: str, workspace_root: Path) -> Path:
    """Преобразует canonical POSIX tool-путь в реальный путь внутри workspace.

    Args:
        file_path: Путь вида ``/dir/file.txt`` после нормализации middleware.
        workspace_root: Реальный корень workspace.

    Returns:
        Абсолютный путь внутри workspace.

    Raises:
        ValueError: Путь выходит за пределы workspace.
    """

    relative_path = str(file_path or "").lstrip("/\\")
    resolved_root = workspace_root.resolve()
    resolved_path = (resolved_root / relative_path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"Путь выходит за пределы workspace: {file_path}") from None
    return resolved_path


def _read_text_preview(file_path: Path, *, max_lines: int) -> dict[str, Any]:
    """Читает первые строки текстового файла для подтверждения записи.

    Args:
        file_path: Реальный путь файла.
        max_lines: Максимальное число строк preview.

    Returns:
        Словарь с preview-строками или ошибкой чтения.
    """

    lines: list[str] = []
    truncated = False
    total_chars = 0
    max_chars = 8000
    try:
        with file_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if line_number > max(0, max_lines):
                    truncated = True
                    break
                clean_line = line.rstrip("\n\r")
                total_chars += len(clean_line)
                if total_chars > max_chars:
                    lines.append(clean_line[: max(0, len(clean_line) - (total_chars - max_chars))])
                    truncated = True
                    break
                lines.append(clean_line)
    except (OSError, UnicodeDecodeError) as error:
        return {
            "available": False,
            "error": f"{type(error).__name__}: {error}",
            "lines": [],
        }
    return {
        "available": True,
        "line_count": len(lines),
        "max_lines": max_lines,
        "truncated": truncated,
        "lines": lines,
    }


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


__all__ = [
    "FilesystemPathContractMiddleware",
    "normalize_filesystem_tool_path",
]
