"""Утилиты сохранения prompt traces в artifacts.

Содержит:
- write_prompt_trace: сохраняет system/human prompt и входной payload узла.
- write_tool_calls_trace: сохраняет фактически выполненные tool calls узла.
- _safe_fragment: преобразует строку в безопасный фрагмент пути.
- _normalize_text: нормализует escaped переносы строк для markdown.
- _render_payload_markdown: рендерит словари и списки в читаемый markdown.
- _render_tool_call_markdown: рендерит один вызов инструмента в markdown.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_service import ArtifactService
from ._json import append_jsonl, read_jsonl

_SUMMARY_MAX_LEN = 1000


def _safe_fragment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "unknown"


def _normalize_text(value: str) -> str:
    """Преобразует escaped переносы строк в реальные для markdown."""
    return (
        str(value)
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
    )


def _render_payload_markdown(value: Any, indent: int = 0) -> str:
    """Рендерит payload в читаемый markdown без JSON."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return f"{pad}(empty)"
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}- **{key}**:")
                lines.append(_render_payload_markdown(item, indent + 1))
            elif isinstance(item, str):
                lines.extend(
                    [
                        f"{pad}- **{key}**:",
                        f"{pad}  ```text",
                        _normalize_text(item),
                        f"{pad}  ```",
                    ]
                )
            else:
                lines.append(f"{pad}- **{key}**: {item}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return f"{pad}(empty)"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_render_payload_markdown(item, indent + 1))
            elif isinstance(item, str):
                lines.extend(
                    [
                        f"{pad}- ```text",
                        _normalize_text(item),
                        f"{pad}  ```",
                    ]
                )
            else:
                lines.append(f"{pad}- {item}")
        return "\n".join(lines)

    if isinstance(value, str):
        return _normalize_text(value)
    return f"{pad}{value}"


def _render_tool_call_markdown(record: dict[str, Any], index: int) -> str:
    """Рендерит один вызов инструмента в читаемый markdown-блок.

    Args:
        record: Словарь с данными вызова инструмента: имя, аргументы, результат
            и служебные идентификаторы.
        index: Порядковый номер вызова в рамках узла.

    Returns:
        Markdown-блок с разделенными полями вызова инструмента.
    """

    tool_name = record.get("tool_name") or record.get("name") or "unknown"
    tool_call_id = record.get("tool_call_id") or record.get("id") or ""
    arguments = record.get("arguments", record.get("args", ""))
    result_preview = record.get(
        "tool_result_preview",
        record.get("result_preview", ""),
    )
    lines = [
        f"## {index}. {tool_name}",
        "",
    ]
    if tool_call_id:
        lines.extend(["**tool_call_id**", "", f"`{tool_call_id}`", ""])
    lines.extend(
        [
            "**Arguments**",
            "",
            "```text",
            _normalize_text(_render_payload_markdown(arguments)),
            "```",
            "",
            "**Result Preview**",
            "",
            "```text",
            _normalize_text(str(result_preview or "(empty)")),
            "```",
        ]
    )
    return "\n".join(lines)


def _extract_task_id(payload: dict[str, Any] | None) -> str:
    """Извлекает task_id из payload trace, если он присутствует.

    Args:
        payload: Диагностический payload, переданный в trace.

    Returns:
        Идентификатор задачи или пустая строка, если trace не относится к task.
    """

    if not isinstance(payload, dict):
        return ""
    task = payload.get("task")
    if isinstance(task, dict):
        task_id = task.get("task_id")
        if task_id:
            return str(task_id)
    return ""


def _append_trace_index(
    *,
    artifact_service: ArtifactService,
    run_id: str,
    stage: str,
    trace_node_id: str,
    task_id: str,
    artifact_role: str,
    artifact_uri: str,
) -> None:
    """Добавляет запись в хронологический индекс trace-файлов запуска.

    Args:
        artifact_service: Сервис artifacts, содержащий путь к каталогу runs.
        run_id: Идентификатор запуска.
        stage: Этап агента: planner, worker, critic и так далее.
        trace_node_id: Идентификатор lineage node, к которому относится trace.
        task_id: Идентификатор worker-задачи, если применимо.
        artifact_role: Роль trace-файла: prompt_trace, prompt_payload, tool_calls_trace.
        artifact_uri: Абсолютный путь к сохраненному markdown artifact.

    Returns:
        ``None``. Функция обновляет индекс на диске.
    """

    created_at = datetime.now(timezone.utc).isoformat()
    run_dir = Path(artifact_service.runs_dir) / run_id
    index_path = run_dir / "trace_index.jsonl"
    entry = {
        "created_at": created_at,
        "stage": stage,
        "node_id": trace_node_id,
        "task_id": task_id,
        "artifact_role": artifact_role,
        "path": artifact_uri,
    }
    append_jsonl(index_path, entry)
    _rewrite_trace_index_markdown(run_dir=run_dir)


def _rewrite_trace_index_markdown(*, run_dir: Path) -> None:
    """Пересобирает markdown-индекс trace-файлов в порядке записи.

    Args:
        run_dir: Каталог текущего запуска внутри ``runs``.

    Returns:
        ``None``. Функция полностью перезаписывает ``trace_index.md``.
    """

    rows = read_jsonl(run_dir / "trace_index.jsonl")
    lines = [
        "# Trace Index",
        "",
        "Хронологический список prompt/tool trace файлов по порядку записи.",
        "",
    ]
    if not rows:
        lines.append("(empty)")
    else:
        for index, row in enumerate(rows, start=1):
            task_suffix = f" | task_id={row.get('task_id')}" if row.get("task_id") else ""
            lines.extend(
                [
                    f"{index}. {row.get('created_at')} | {row.get('stage')} | "
                    f"{row.get('artifact_role')} | node_id={row.get('node_id')}{task_suffix}",
                    f"   {row.get('path')}",
                    "",
                ]
            )
    (run_dir / "trace_index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_prompt_trace(
    *,
    artifact_service: ArtifactService | None,
    run_id: str | None,
    node_id: str | None,
    stage: str,
    system_prompt: str,
    human_prompt: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Сохраняет prompt и входные данные шага как artifacts.

    Args:
        artifact_service: Сервис записи artifacts или ``None``.
        run_id: Идентификатор текущего запуска.
        node_id: Идентификатор lineage-узла текущего шага.
        stage: Название этапа агента, например ``planner`` или ``worker``.
        system_prompt: Итоговый system prompt узла.
        human_prompt: Итоговый human prompt узла.
        payload: Дополнительные входные данные узла для диагностики.

    Returns:
        Индекс созданных artifacts (artifact_id -> artifact as json dict).
    """
    if artifact_service is None or not run_id:
        return {}

    stage_safe = _safe_fragment(stage)
    trace_node_id = node_id or f"prompt_trace_{stage_safe}"
    trace_path = f"prompt_traces/{stage_safe}/{_safe_fragment(trace_node_id)}"
    task_id = _extract_task_id(payload)
    artifacts: dict[str, Any] = {}

    prompt_text = (
        "# Prompt Trace\n\n"
        f"## Stage\n\n{stage}\n\n"
        f"## Node ID\n\n{trace_node_id}\n\n"
        "## System Prompt\n\n"
        "```text\n"
        f"{_normalize_text(system_prompt)}\n"
        "```\n\n"
        "## Human Prompt\n\n"
        "```text\n"
        f"{_normalize_text(human_prompt or '(empty)')}\n"
        "```\n"
    )
    prompt_artifact = artifact_service.write_artifact(
        run_id=run_id,
        node_id=trace_node_id,
        kind="model_output",
        filename=f"{trace_path}/prompt.md",
        content=prompt_text,
        mime_type="text/markdown",
        summary=(
            f"prompt_trace | stage={stage} | node_id={trace_node_id} | "
            f"full prompts in artifact file (not inlined in summary)"
        )[:_SUMMARY_MAX_LEN],
        metadata={
            "artifact_role": "prompt_trace",
            "stage": stage,
            "trace_node_id": trace_node_id,
        },
    )
    artifacts[prompt_artifact.artifact_id] = prompt_artifact.model_dump(mode="json")
    _append_trace_index(
        artifact_service=artifact_service,
        run_id=run_id,
        stage=stage,
        trace_node_id=trace_node_id,
        task_id=task_id,
        artifact_role="prompt_trace",
        artifact_uri=prompt_artifact.uri,
    )

    payload_data = payload or {}
    payload_rendered = _render_payload_markdown(payload_data)
    payload_text = (
        "# Prompt Payload\n\n"
        f"## Stage\n\n{stage}\n\n"
        f"## Node ID\n\n{trace_node_id}\n\n"
        "## Input Data\n\n"
        f"{payload_rendered}\n"
    )
    payload_artifact = artifact_service.write_artifact(
        run_id=run_id,
        node_id=trace_node_id,
        kind="model_output",
        filename=f"{trace_path}/payload.md",
        content=payload_text,
        mime_type="text/markdown",
        summary=(
            f"prompt_payload | stage={stage} | node_id={trace_node_id} | "
            f"payload markdown in artifact file"
        )[:_SUMMARY_MAX_LEN],
        metadata={
            "artifact_role": "prompt_payload",
            "stage": stage,
            "trace_node_id": trace_node_id,
        },
    )
    artifacts[payload_artifact.artifact_id] = payload_artifact.model_dump(mode="json")
    _append_trace_index(
        artifact_service=artifact_service,
        run_id=run_id,
        stage=stage,
        trace_node_id=trace_node_id,
        task_id=task_id,
        artifact_role="prompt_payload",
        artifact_uri=payload_artifact.uri,
    )
    return artifacts


def write_tool_calls_trace(
    *,
    artifact_service: ArtifactService | None,
    run_id: str | None,
    node_id: str | None,
    stage: str,
    tool_calls: list[dict[str, Any]] | None,
    task_id: str = "",
) -> dict[str, Any]:
    """Сохраняет список фактически выполненных инструментов как markdown artifact.

    Args:
        artifact_service: Сервис записи artifacts или ``None``.
        run_id: Идентификатор текущего запуска.
        node_id: Идентификатор узла, внутри которого выполнялись инструменты.
        stage: Имя этапа агента, например ``worker`` или ``responder``.
        tool_calls: Список вызовов инструментов с аргументами и preview результата.
        task_id: Идентификатор worker-задачи, если trace относится к конкретной задаче.

    Returns:
        Индекс созданных artifacts (artifact_id -> artifact as json dict).
    """

    if artifact_service is None or not run_id:
        return {}

    stage_safe = _safe_fragment(stage)
    trace_node_id = node_id or f"tool_calls_{stage_safe}"
    trace_path = f"prompt_traces/{stage_safe}/{_safe_fragment(trace_node_id)}"
    calls = tool_calls or []
    if calls:
        calls_text = "\n\n---\n\n".join(
            _render_tool_call_markdown(record, index)
            for index, record in enumerate(calls, start=1)
        )
    else:
        calls_text = "(tools were not called)"

    content = (
        "# Tool Calls Trace\n\n"
        f"## Stage\n\n{stage}\n\n"
        f"## Node ID\n\n{trace_node_id}\n\n"
        f"## Total Calls\n\n{len(calls)}\n\n"
        f"{calls_text}\n"
    )
    artifact = artifact_service.write_artifact(
        run_id=run_id,
        node_id=trace_node_id,
        kind="tool_trace",
        filename=f"{trace_path}/tool_calls.md",
        content=content,
        mime_type="text/markdown",
        summary=(
            f"tool_calls_trace | stage={stage} | node_id={trace_node_id} | "
            f"calls={len(calls)} | details in artifact file"
        )[:_SUMMARY_MAX_LEN],
        metadata={
            "artifact_role": "tool_calls_trace",
            "stage": stage,
            "tool_call_count": len(calls),
            "trace_node_id": trace_node_id,
        },
    )
    _append_trace_index(
        artifact_service=artifact_service,
        run_id=run_id,
        stage=stage,
        trace_node_id=trace_node_id,
        task_id=task_id,
        artifact_role="tool_calls_trace",
        artifact_uri=artifact.uri,
    )
    return {artifact.artifact_id: artifact.model_dump(mode="json")}
