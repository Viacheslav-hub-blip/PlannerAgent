"""Утилиты сохранения prompt traces в artifacts."""

from __future__ import annotations

import re
from typing import Any

from .artifact_service import ArtifactService

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

    Returns:
        Индекс созданных artifacts (artifact_id -> artifact as json dict).
    """
    if artifact_service is None or not run_id:
        return {}

    stage_safe = _safe_fragment(stage)
    trace_node_id = node_id or f"prompt_trace_{stage_safe}"
    artifacts: dict[str, Any] = {}

    prompt_text = (
        "# Prompt Trace\n\n"
        f"## Stage\n\n{stage}\n\n"
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
        filename=f"prompt_traces/{stage_safe}/prompt.md",
        content=prompt_text,
        mime_type="text/markdown",
        summary=prompt_text[:_SUMMARY_MAX_LEN],
        metadata={
            "artifact_role": "prompt_trace",
            "stage": stage,
        },
    )
    artifacts[prompt_artifact.artifact_id] = prompt_artifact.model_dump(mode="json")

    payload_data = payload or {}
    payload_rendered = _render_payload_markdown(payload_data)
    payload_text = (
        "# Prompt Payload\n\n"
        f"## Stage\n\n{stage}\n\n"
        "## Input Data\n\n"
        f"{payload_rendered}\n"
    )
    payload_artifact = artifact_service.write_artifact(
        run_id=run_id,
        node_id=trace_node_id,
        kind="model_output",
        filename=f"prompt_traces/{stage_safe}/payload.md",
        content=payload_text,
        mime_type="text/markdown",
        summary=payload_text[:_SUMMARY_MAX_LEN],
        metadata={
            "artifact_role": "prompt_payload",
            "stage": stage,
        },
    )
    artifacts[payload_artifact.artifact_id] = payload_artifact.model_dump(mode="json")
    return artifacts
