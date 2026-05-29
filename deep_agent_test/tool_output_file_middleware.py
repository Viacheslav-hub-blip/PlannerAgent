"""Middleware сохранения больших табличных результатов tool-вызовов в pickle."""

from __future__ import annotations

import ast
import json
import pickle
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


@dataclass(frozen=True)
class ToolOutputFileMiddleware(AgentMiddleware):
    """Сохраняет большие табличные tool outputs в pickle и возвращает модели краткую ссылку."""

    output_dir: Path
    min_rows_to_save: int = 10
    min_content_chars_to_save: int = 60000
    preview_rows: int = 3
    inline_original_content_chars: int = 1000

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        result = handler(request)
        if isinstance(result, ToolMessage):
            return self._process_tool_message(result=result, tool_name=str(request.tool_call.get("name") or "tool"))
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if isinstance(result, ToolMessage):
            return self._process_tool_message(result=result, tool_name=str(request.tool_call.get("name") or "tool"))
        return result

    def _process_tool_message(self, *, result: ToolMessage, tool_name: str) -> ToolMessage:
        rows = _extract_tabular_payload(result.artifact, result.content)
        content_text = str(result.content)
        if not rows:
            return result
        if len(rows) <= self.min_rows_to_save and len(content_text) <= self.min_content_chars_to_save:
            return result

        self.output_dir.mkdir(parents=True, exist_ok=True)
        file_path = _write_rows_to_pkl(
            rows=rows,
            output_dir=self.output_dir,
            tool_name=tool_name,
        )
        summary = _build_file_summary(
            tool_name=tool_name,
            file_path=file_path,
            rows=rows,
            preview_rows=self.preview_rows,
            original_content=content_text,
            inline_original_content_chars=self.inline_original_content_chars,
        )
        artifact = {
            "saved_file": str(file_path),
            "format": "pkl",
            "rows": len(rows),
            "columns": sorted({key for row in rows for key in row}),
            "source_artifact_type": type(result.artifact).__name__,
        }
        return ToolMessage(
            content=summary,
            artifact=artifact,
            tool_call_id=result.tool_call_id,
            name=result.name,
            status=result.status,
            additional_kwargs=result.additional_kwargs,
            response_metadata=result.response_metadata,
        )


def _extract_tabular_payload(artifact: Any, content: Any) -> list[dict[str, Any]]:
    rows = _extract_rows_from_value(artifact)
    if rows:
        return rows
    if not isinstance(content, str):
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(content)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        rows = _extract_rows_from_value(parsed)
        if rows:
            return rows
    return []


def _extract_rows_from_value(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            records = value.to_dict(orient="records")
        except TypeError:
            records = None
        if isinstance(records, list):
            return [_row_to_mapping(item) for item in records]
    if isinstance(value, list):
        return [_row_to_mapping(item) for item in value]
    if isinstance(value, dict):
        for key in ("rows", "records", "data", "result"):
            rows = _extract_rows_from_value(value.get(key))
            if rows:
                return rows
    return []


def _write_rows_to_pkl(*, rows: list[dict[str, Any]], output_dir: Path, tool_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = output_dir / f"{timestamp}_{_safe_filename_part(tool_name)}.pkl"
    with file_path.open("wb") as file:
        pickle.dump(rows, file)
    return file_path.resolve()


def _build_file_summary(
    *,
    tool_name: str,
    file_path: Path,
    rows: list[dict[str, Any]],
    preview_rows: int,
    original_content: str,
    inline_original_content_chars: int,
) -> str:
    preview = rows[: max(0, preview_rows)]
    columns = sorted({key for row in rows for key in row})
    preview_text = json.dumps(preview, ensure_ascii=False, indent=2, default=str)
    original_note = ""
    if original_content and len(original_content) <= inline_original_content_chars:
        original_note = f"\n\nКраткий исходный вывод tool:\n{original_content}"
    resolved_path = file_path.resolve()
    return (
        f"Tool `{tool_name}` вернул большой табличный результат и он сохранен в pickle.\n"
        f"Файл: {resolved_path.name}\n"
        f"Путь: {resolved_path}\n"
        f"Формат: pickle (list[dict]).\n"
        f"Строк: {len(rows)}; колонок: {len(columns)}.\n"
        f"Колонки: {', '.join(map(str, columns))}.\n"
        "Для получения полного результата используй `execute_python_code`. "
        "Helpers уже доступны в sandbox: read_pickle_file, describe_pickle_file, "
        "rows_to_dataframe, pd, np. Пример:\n"
        f"rows = read_pickle_file(r\"{resolved_path}\")\n"
        "df = rows_to_dataframe(rows)\n"
        "При ошибке execute_python_code читай traceback из ответа tool и исправляй код.\n"
        f"Preview первых {len(preview)} строк:\n{preview_text}"
        f"{original_note}"
    )


def _safe_filename_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return safe[:80] or "tool"


def _row_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


__all__ = ["ToolOutputFileMiddleware"]
