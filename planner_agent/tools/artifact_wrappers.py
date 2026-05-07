"""Обертки LangChain tools для записи tool traces и больших outputs как artifacts.

Содержит:
- ArtifactToolWrapper: wrapper над обычным LangChain tool.
- wrap_tools_for_artifacts: массовое оборачивание tools для worker.
- _clean_runtime_kwargs: удаление runtime-only kwargs.
- _tool_input_from_call: восстановление входа tool из args/kwargs.
- _safe_filename_fragment: безопасный фрагмент имени файла.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from langchain_core.tools import BaseTool
from pydantic import PrivateAttr

from ..models import Task
from ..runtime.tool_result_capture import (
    build_tool_trace_content,
    capture_tool_result,
    serialize_tool_result,
)
from ..services.artifact_service import ArtifactService

TOOL_ARTIFACT_SUMMARY_MAX_LEN = 500


class ArtifactToolWrapper(BaseTool):
    """Обертка над LangChain tool, которая защищает контекст worker от больших outputs."""

    _wrapped_tool: BaseTool = PrivateAttr()
    _artifact_service: ArtifactService = PrivateAttr()
    _run_id: str = PrivateAttr()
    _node_id: str = PrivateAttr()
    _task: Task = PrivateAttr()
    _artifact_index: dict[str, Any] = PrivateAttr()
    _tool_traces: list[dict[str, Any]] = PrivateAttr()

    def __init__(
            self,
            *,
            wrapped_tool: BaseTool,
            artifact_service: ArtifactService,
            run_id: str,
            node_id: str,
            task: Task,
            artifact_index: dict[str, Any],
            tool_traces: list[dict[str, Any]],
    ) -> None:
        """Создает wrapper над обычным LangChain tool.

        Args:
            wrapped_tool: Исходный LangChain tool.
            artifact_service: Сервис записи artifacts.
            run_id: Идентификатор ResearchRun.
            node_id: Идентификатор worker_started node.
            task: Текущая задача worker.
            artifact_index: Общий индекс artifacts для обновления state.
            tool_traces: Список trace-событий для обновления state.

        Returns:
            None.
        """

        super().__init__(
            name=wrapped_tool.name,
            description=(
                f"{wrapped_tool.description} "
                "Runtime note: large outputs are automatically captured into run "
                "artifacts and replaced with compact references in LLM context. "
                "Use artifact read tools to inspect full payloads."
            ).strip(),
            args_schema=wrapped_tool.args_schema,
            return_direct=wrapped_tool.return_direct,
            response_format=wrapped_tool.response_format,
        )
        self._wrapped_tool = wrapped_tool
        self._artifact_service = artifact_service
        self._run_id = run_id
        self._node_id = node_id
        self._task = task
        self._artifact_index = artifact_index
        self._tool_traces = tool_traces

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Синхронно вызывает tool и возвращает безопасный для LLM результат.

        Args:
            *args: Позиционные аргументы tool.
            **kwargs: Именованные аргументы tool.

        Returns:
            Исходный маленький результат или artifact reference для большого результата.
        """

        clean_kwargs = _clean_runtime_kwargs(kwargs)
        tool_input = _tool_input_from_call(args, clean_kwargs)
        result = self._wrapped_tool.invoke(tool_input)
        return self._record_tool_result(tool_input=tool_input, result=result)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """Асинхронно вызывает tool и возвращает безопасный для LLM результат.

        Args:
            *args: Позиционные аргументы tool.
            **kwargs: Именованные аргументы tool.

        Returns:
            Исходный маленький результат или artifact reference для большого результата.
        """

        clean_kwargs = _clean_runtime_kwargs(kwargs)
        tool_input = _tool_input_from_call(args, clean_kwargs)
        result = await self._wrapped_tool.ainvoke(tool_input)
        return self._record_tool_result(tool_input=tool_input, result=result)

    def _record_tool_result(self, *, tool_input: Any, result: Any) -> Any:
        """Записывает tool trace и artifacts, затем возвращает результат для LLM.

        Args:
            tool_input: Аргументы вызова tool.
            result: Сырой результат tool.

        Returns:
            Значение, которое будет передано worker-агенту.
        """

        trace_id = uuid4().hex
        captured = capture_tool_result(
            artifact_service=self._artifact_service,
            run_id=self._run_id,
            node_id=self._node_id,
            task_id=self._task.task_id,
            tool_name=self.name,
            tool_input=tool_input,
            raw_result=result,
            capture_id=trace_id,
        )
        content = build_tool_trace_content(
            tool_name=self.name,
            tool_input=tool_input,
            captured=captured,
        )
        artifact = self._artifact_service.write_artifact(
            run_id=self._run_id,
            node_id=self._node_id,
            kind="tool_trace",
            filename=(
                f"tasks/{_safe_filename_fragment(self._task.task_id or 'unknown_task')}"
                f"/tool_calls/{_safe_filename_fragment(self.name)}-{trace_id}.txt"
            ),
            content=content,
            mime_type="text/plain",
            summary=captured.preview[:TOOL_ARTIFACT_SUMMARY_MAX_LEN],
            metadata={
                "trace_id": trace_id,
                "task_id": self._task.task_id,
                "tool_name": self.name,
                "args_preview": serialize_tool_result(
                    tool_input,
                    max_chars=TOOL_ARTIFACT_SUMMARY_MAX_LEN,
                ),
                "artifact_role": "tool_call_trace",
                "captured": captured.was_captured,
                "captured_artifact_refs": captured.artifact_refs,
                "original_size_estimate": captured.original_size_estimate,
                "reusable": True,
            },
        )
        self._artifact_index.update(captured.artifact_index)
        self._artifact_index[artifact.artifact_id] = artifact.model_dump(mode="json")
        for artifact_id in captured.artifact_refs:
            self._task.artifact_refs.append(artifact_id)
        self._task.artifact_refs.append(artifact.artifact_id)
        self._tool_traces.append(
            {
                "trace_id": trace_id,
                "run_id": self._run_id,
                "node_id": self._node_id,
                "task_id": self._task.task_id,
                "tool_name": self.name,
                "args_preview": serialize_tool_result(
                    tool_input,
                    max_chars=TOOL_ARTIFACT_SUMMARY_MAX_LEN,
                ),
                "result_preview": captured.preview[:TOOL_ARTIFACT_SUMMARY_MAX_LEN],
                "artifact_id": artifact.artifact_id,
                "artifact_uri": artifact.uri,
                "captured": captured.was_captured,
                "captured_artifact_refs": captured.artifact_refs,
                "original_size_estimate": captured.original_size_estimate,
            }
        )
        return captured.content_for_llm


def wrap_tools_for_artifacts(
        *,
        tools: list[BaseTool],
        artifact_service: ArtifactService | None,
        run_id: str,
        node_id: str | None,
        task: Task,
        artifact_index: dict[str, Any],
        tool_traces: list[dict[str, Any]],
) -> list[BaseTool]:
    """Оборачивает tools в ArtifactToolWrapper при наличии artifact service.

    Args:
        tools: Исходные LangChain tools.
        artifact_service: Сервис artifacts или ``None``.
        run_id: Идентификатор ResearchRun.
        node_id: Идентификатор worker node.
        task: Текущая задача worker.
        artifact_index: Индекс artifacts для обновления state.
        tool_traces: Список trace-событий для обновления state.

    Returns:
        Список исходных или обернутых tools.
    """

    if artifact_service is None or not run_id or not node_id:
        return tools

    return [
        ArtifactToolWrapper(
            wrapped_tool=tool,
            artifact_service=artifact_service,
            run_id=run_id,
            node_id=node_id,
            task=task,
            artifact_index=artifact_index,
            tool_traces=tool_traces,
        )
        for tool in tools
    ]


def _clean_runtime_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Удаляет kwargs, которые LangChain передает в runtime, но не в tool input.

    Args:
        kwargs: Именованные аргументы wrapper-вызова.

    Returns:
        Очищенный словарь аргументов.
    """

    return {
        key: value
        for key, value in kwargs.items()
        if key not in {"run_manager", "callbacks", "config"}
    }


def _tool_input_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Восстанавливает фактический input tool из args/kwargs.

    Args:
        args: Позиционные аргументы wrapper-вызова.
        kwargs: Очищенные именованные аргументы wrapper-вызова.

    Returns:
        Значение, которое нужно передать в исходный LangChain tool.
    """

    if kwargs:
        return kwargs
    if len(args) == 1:
        return args[0]
    return list(args)


def _safe_filename_fragment(value: str) -> str:
    """Преобразует строку в безопасный фрагмент имени файла.

    Args:
        value: Исходная строка.

    Returns:
        Безопасный фрагмент имени файла.
    """

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "unknown"
