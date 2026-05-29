"""Сборка native DeepAgents агента для аналитики данных."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from deep_agent_test.agent_specs import build_analytics_subagent_specs
from deep_agent_test.execute_python_code_tool import build_execute_python_code_tool
from deep_agent_test.prompts import READ_TABLE_DESCRIPTION, SYSTEM_PROMPT
from deep_agent_test.python_sandbox import build_python_sandbox
from deep_agent_test.settings import DeepAgentSettings, load_deep_agent_settings
from deep_agent_test.skills_context_middleware import PreloadedSkillsContextMiddleware
from deep_agent_test.tool_output_file_middleware import ToolOutputFileMiddleware


def build_read_table_description() -> str:
    """Возвращает подробное описание инструмента ``read_table`` для LLM."""

    return READ_TABLE_DESCRIPTION


def build_data_tools(settings: DeepAgentSettings | None = None) -> list[BaseTool]:
    """Собирает инструменты чтения данных через фабрику из JSON-конфига."""

    settings = settings or load_deep_agent_settings()
    if not settings.data_tools_factory:
        raise ValueError(
            "Не настроена фабрика tools чтения данных. "
            "Передайте data_tools в build_analytics_deep_agent или укажите "
            "data_tools_factory в deep_agent_test/config/defaults.json или override-конфиге."
        )
    factory = _load_callable_from_path(settings.data_tools_factory)
    return _normalize_data_tools(factory(**settings.data_tools_factory_kwargs))


def _load_callable_from_path(import_path: str) -> Callable[..., Any]:
    if ":" in import_path:
        module_name, attribute_name = import_path.split(":", 1)
    else:
        try:
            module_name, attribute_name = import_path.rsplit(".", 1)
        except ValueError:
            raise ValueError(f"Некорректный import path фабрики tools: {import_path}") from None
    if not module_name or not attribute_name:
        raise ValueError(f"Некорректный import path фабрики tools: {import_path}")

    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name)
    if not callable(factory):
        raise TypeError(f"Объект {import_path} не является callable.")
    return factory


def _normalize_data_tools(raw_tools: Any) -> list[BaseTool]:
    if isinstance(raw_tools, BaseTool):
        return [raw_tools]
    if not isinstance(raw_tools, (list, tuple)):
        raise TypeError("Фабрика tools должна вернуть BaseTool или список BaseTool.")

    tools: list[BaseTool] = []
    for item in raw_tools:
        if not isinstance(item, BaseTool):
            raise TypeError(f"Фабрика tools вернула объект не BaseTool: {type(item).__name__}")
        tools.append(item)
    return tools


def build_analytics_deep_agent(
    model: Any,
    settings: DeepAgentSettings | None = None,
    data_tools: list[BaseTool] | None = None,
) -> Any:
    """Собирает DeepAgent supervisor для аналитики данных."""

    settings = settings or load_deep_agent_settings()
    if data_tools is None:
        data_tools = build_data_tools(settings)

    skills_context_middleware = PreloadedSkillsContextMiddleware(
        skills_root=settings.skills_root,
        skills_virtual_dir=settings.skills_virtual_dir,
        max_chars_per_file=settings.max_chars_per_skill,
        model=model,
    )
    tool_output_file_middleware = ToolOutputFileMiddleware(
        output_dir=settings.tool_outputs_dir,
        min_rows_to_save=settings.tool_output_min_rows_to_save,
        min_content_chars_to_save=settings.tool_output_min_content_chars_to_save,
        preview_rows=settings.tool_output_preview_rows,
        inline_original_content_chars=settings.tool_output_inline_original_chars,
    )
    common_subagent_middleware = [skills_context_middleware, tool_output_file_middleware]
    subagents = build_analytics_subagent_specs(
        settings=settings,
        data_tools=data_tools,
        common_middleware=common_subagent_middleware,
    )
    python_sandbox = build_python_sandbox(settings)
    python_tool = build_execute_python_code_tool(python_sandbox)

    return create_deep_agent(
        model=model,
        tools=[python_tool],
        system_prompt=SYSTEM_PROMPT,
        subagents=subagents,
        skills=[settings.skills_virtual_dir],
        backend=build_skills_backend(settings),
        permissions=build_skills_permissions(settings),
        middleware=[skills_context_middleware, tool_output_file_middleware],
        checkpointer=MemorySaver(),
    )


def get_skills_root(settings: DeepAgentSettings | None = None) -> Path:
    settings = settings or load_deep_agent_settings()
    return settings.skills_root


def build_skills_backend(settings: DeepAgentSettings | None = None) -> Any:
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

    settings = settings or load_deep_agent_settings()
    return CompositeBackend(
        default=StateBackend(),
        routes={
            settings.skills_virtual_dir: FilesystemBackend(
                root_dir=settings.skills_root,
                virtual_mode=True,
            )
        },
    )


def build_skills_permissions(settings: DeepAgentSettings | None = None) -> list[Any]:
    from deepagents import FilesystemPermission

    settings = settings or load_deep_agent_settings()
    return [
        FilesystemPermission(
            operations=["write"],
            paths=[f"{settings.skills_virtual_dir}**"],
            mode="deny",
        )
    ]


def invoke_agent(agent: Any, message: str, thread_id: str) -> Any:
    return agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
    )


def resume_with_decision(agent: Any, thread_id: str, decision: dict[str, Any]) -> Any:
    return agent.invoke(
        Command(resume={"decisions": [decision]}),
        config={"configurable": {"thread_id": thread_id}},
    )


def resume_with_user_answer(agent: Any, thread_id: str, answer: str) -> Any:
    return resume_with_decision(
        agent=agent,
        thread_id=thread_id,
        decision={"type": "respond", "message": answer},
    )


__all__ = [
    "build_skills_backend",
    "build_skills_permissions",
    "build_analytics_deep_agent",
    "build_data_tools",
    "build_execute_python_code_tool",
    "build_python_sandbox",
    "build_read_table_description",
    "get_skills_root",
    "invoke_agent",
    "resume_with_decision",
    "resume_with_user_answer",
]
