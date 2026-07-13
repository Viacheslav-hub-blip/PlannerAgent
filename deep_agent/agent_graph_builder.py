"""Этапы сборки DeepAgent graph.

Содержит функции и классы:
- _AgentBuildContext: контейнер настроек и путей одного запуска.
- _AgentBackends: контейнер backend-ов graph.
- _AgentTools: контейнер tools graph.
- _SkillsMiddlewareBundle: контейнер skills middleware.
- _build_agent_context: подготовка настроек, модели и путей.
- _build_agent_backends: сборка backend-ов.
- _build_agent_tools: сборка tools.
- _build_skills_middleware: сборка skills middleware.
- _build_subagent_graphs: сборка compiled subagents.
- _build_coding_agent_graph: сборка coding-agent.
- _build_data_retrieval_agent_graph: сборка data-retrieval-agent.
- _build_supervisor_graph: сборка supervisor graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.memory import MemoryMiddleware
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent.agent_settings import AgentSettings, load_agent_settings, workspace_tool_path
from deep_agent.execution.python_sandbox import build_python_sandbox
from deep_agent.middleware.skills_context_middleware import PreloadedSkillsContextMiddleware
from deep_agent.middleware.request_logging_middleware import (
    AgentRequestLogger,
    AgentRequestLoggingMiddleware,
)
from deep_agent.middleware.todo_reset_middleware import TodoResetMiddleware
from deep_agent.middleware.user_profile_memory_middleware import UserProfileMemoryMiddleware
from deep_agent.prompts.skills_context_prompt import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.supervisor_prompt import SYSTEM_PROMPT
from deep_agent.prompts.coding_agent_prompt import CODING_AGENT_PROMPT
from deep_agent.prompts.data_retrieval_agent_prompt import DATA_RETRIEVAL_PROMPT
from deep_agent.subagents import (
    CODING_AGENT_DESCRIPTION,
    CODING_AGENT_NAME,
    DATA_RETRIEVAL_AGENT_DESCRIPTION,
    DATA_RETRIEVAL_AGENT_NAME,
)
from deep_agent.tools.jupyter_notebook_tool import ConvertJupyterNotebookTool
from deep_agent.tools.python_execution_tool import PythonTool
from deep_agent.tools.project_structure_tool import GetProjectStructureTool
from deep_agent.tools.skill_loader_tool import build_load_skills_tool
from deep_agent.agent import (
    _DEFAULT_CHECKPOINTER,
    _agents_memory_path,
    _build_native_runtime_middleware,
    _rebase_tool_outputs_path,
    _rebase_workspace_path,
    _resolve_workspace_root,
    build_filesystem_workspace_backend,
    build_shell_workspace_backend,
)
from deep_agent.execution.filesystem_backend import configure_read_file_default_limit


@dataclass(frozen=True)
class _AgentBuildContext:
    """Хранит вычисленные пути и настройки одного запуска сборки агента.

    Args:
        settings: Настройки агента.
        model: Chat-модель LangChain для supervisor и subagents.
        workspace_root: Фактический корень workspace.
        skills_root: Фактическая директория skills.
        tool_outputs_dir: Каталог артефактов инструментов текущего запуска.
        skills_workspace_dir: Виртуальный workspace-путь к skills.
        agents_memory_path: Виртуальный workspace-путь к project memory.
        state_artifacts_virtual_dir: Виртуальная директория state-артефактов UI.
        checkpointer: Checkpointer LangGraph или маркер штатной памяти.
        system_prompt_suffix: Дополнительный prompt supervisor.
        request_logger: Логгер пользовательских запросов или ``None``.
        user_profile_memory: Ссылка на память профиля пользователя или ``None``.
        user_profile_spark_session_factory: Фабрика SparkSession для профиля или ``None``.
        user_memory_paths: Список виртуальных файлов памяти пользователя.

    Returns:
        Контейнер без поведения, используемый helper-функциями сборки.
    """

    settings: AgentSettings
    model: Any
    workspace_root: Path
    skills_root: Path
    tool_outputs_dir: Path
    skills_workspace_dir: str
    agents_memory_path: str
    state_artifacts_virtual_dir: str | None
    checkpointer: Any
    system_prompt_suffix: str | None
    request_logger: AgentRequestLogger | None
    user_profile_memory: Any | None
    user_profile_spark_session_factory: Any | None
    user_memory_paths: list[str] | None


@dataclass(frozen=True)
class _AgentBackends:
    """Хранит backend-ы для supervisor, coding-agent и data-retrieval-agent.

    Args:
        supervisor: Backend главного агента.
        coding: Backend coding-agent с shell.
        data: Backend data-retrieval-agent без shell.

    Returns:
        Контейнер backend-ов для передачи в сборку graph.
    """

    supervisor: Any
    coding: Any
    data: Any


@dataclass(frozen=True)
class _AgentTools:
    """Хранит инструменты, общие для supervisor и subagents.

    Args:
        data_tools: Инструменты чтения данных после нормализации.
        supervisor_tools: Внешние инструменты, доступные только supervisor.
        python_tool: Инструмент Python REPL.
        load_skills_tool: Инструмент загрузки skills.
        project_structure_tool: Инструмент просмотра структуры проекта.
        jupyter_notebook_tool: Инструмент конвертации notebooks.

    Returns:
        Контейнер tools для helper-функций сборки.
    """

    data_tools: list[BaseTool]
    supervisor_tools: list[BaseTool]
    python_tool: Any
    load_skills_tool: Any
    project_structure_tool: Any
    jupyter_notebook_tool: Any


@dataclass(frozen=True)
class _SkillsMiddlewareBundle:
    """Хранит middleware предзагрузки skills для supervisor и data-agent.

    Args:
        supervisor: Middleware выбора и предзагрузки skills для supervisor.
        subagent: Middleware чтения уже выбранных skills для subagents.

    Returns:
        Контейнер middleware для сборки graph.
    """

    supervisor: Any
    subagent: Any



def _build_agent_context(
    *,
    model: Any | None,
    settings: AgentSettings | None,
    workspace_root: str | Path | None,
    checkpointer: Any,
    state_artifacts_virtual_dir: str | None,
    system_prompt_suffix: str | None,
    request_logger: AgentRequestLogger | None = None,
    user_profile_memory: Any | None = None,
    user_profile_spark_session_factory: Any | None = None,
    user_memory_paths: list[str] | None = None,
) -> _AgentBuildContext:
    """Готовит настройки, модель и вычисленные пути одного запуска агента.

    Args:
        model: Chat-модель LangChain или ``None`` для штатной GigaChat KitAI модели.
        settings: Готовые настройки агента или ``None`` для загрузки defaults.
        workspace_root: Корень workspace, переопределяющий значение из settings.
        checkpointer: Checkpointer LangGraph или маркер штатного ``InMemorySaver``.
        state_artifacts_virtual_dir: Виртуальная директория state-артефактов UI.
        system_prompt_suffix: Дополнительный prompt supervisor.
        request_logger: Логгер пользовательских запросов или ``None``.
        user_profile_memory: Ссылка на память профиля пользователя или ``None``.
        user_profile_spark_session_factory: Фабрика SparkSession для профиля или ``None``.
        user_memory_paths: Список виртуальных файлов памяти пользователя.

    Returns:
        Контекст сборки с нормализованными путями и моделью.
    """

    resolved_settings = settings or load_agent_settings(workspace_root)
    if model is None:
        raise ValueError("Параметр model должен быть передан в build_agent явно.")
    resolved_model = model
    configure_read_file_default_limit(resolved_settings.read_file_default_limit)
    resolved_workspace_root = _resolve_workspace_root(workspace_root or resolved_settings.workspace_root)
    resolved_skills_root = _rebase_workspace_path(
        resolved_settings.skills_root,
        resolved_settings.workspace_root,
        resolved_workspace_root,
    )
    resolved_tool_outputs_root = _rebase_tool_outputs_path(
        resolved_settings.tool_outputs_dir,
        resolved_settings.workspace_root,
        resolved_workspace_root,
    )
    resolved_tool_outputs_root.mkdir(parents=True, exist_ok=True)
    tool_outputs_dir = resolved_tool_outputs_root.resolve()
    skills_workspace_dir = workspace_tool_path(
        resolved_skills_root,
        resolved_workspace_root,
        directory=True,
    )
    agents_memory_path = _agents_memory_path(
        resolved_settings.agents_file_name,
        resolved_workspace_root,
    )
    return _AgentBuildContext(
        settings=resolved_settings,
        model=resolved_model,
        workspace_root=resolved_workspace_root,
        skills_root=resolved_skills_root,
        tool_outputs_dir=tool_outputs_dir,
        skills_workspace_dir=skills_workspace_dir,
        agents_memory_path=agents_memory_path,
        state_artifacts_virtual_dir=state_artifacts_virtual_dir,
        checkpointer=checkpointer,
        system_prompt_suffix=system_prompt_suffix,
        request_logger=request_logger,
        user_profile_memory=user_profile_memory,
        user_profile_spark_session_factory=user_profile_spark_session_factory,
        user_memory_paths=user_memory_paths,
    )


def _build_agent_backends(context: _AgentBuildContext) -> _AgentBackends:
    """Собирает backend-ы для supervisor, coding-agent и data-retrieval-agent.

    Args:
        context: Контекст сборки агента.

    Returns:
        Контейнер backend-ов по зонам ответственности.
    """

    return _AgentBackends(
        data=build_filesystem_workspace_backend(
            context.settings,
            workspace_root=context.workspace_root,
        ),
        supervisor=build_shell_workspace_backend(
            context.settings,
            workspace_root=context.workspace_root,
            state_artifacts_virtual_dir=context.state_artifacts_virtual_dir,
        ),
        coding=build_shell_workspace_backend(
            context.settings,
            workspace_root=context.workspace_root,
        ),
    )


def _build_agent_tools(
    context: _AgentBuildContext,
    *,
    data_tools: list[BaseTool],
    supervisor_tools: list[BaseTool],
) -> _AgentTools:
    """Собирает tools, которые используются supervisor и subagents.

    Args:
        context: Контекст сборки агента.
        data_tools: Уже нормализованные инструменты чтения данных.
        supervisor_tools: Уже нормализованные внешние инструменты для supervisor.

    Returns:
        Контейнер tools для сборки graph.
    """

    python_sandbox = build_python_sandbox(
        context.settings,
        tool_outputs_dir=context.tool_outputs_dir,
        workspace_root=context.workspace_root,
    )
    return _AgentTools(
        data_tools=data_tools,
        supervisor_tools=supervisor_tools,
        python_tool=PythonTool(sandbox=python_sandbox),
        load_skills_tool=build_load_skills_tool(
            context.settings,
            skills_root=context.skills_root,
            workspace_root=context.workspace_root,
        ),
        project_structure_tool=GetProjectStructureTool(
            workspace_root=context.workspace_root,
            agent_root=context.skills_root.parent,
            skills_root=context.skills_root,
        ),
        jupyter_notebook_tool=ConvertJupyterNotebookTool(
            workspace_root=context.workspace_root,
        ),
    )


def _build_skills_middleware(context: _AgentBuildContext) -> _SkillsMiddlewareBundle:
    """Создает middleware предзагрузки skills для supervisor и subagents.

    Args:
        context: Контекст сборки агента.

    Returns:
        Контейнер middleware для supervisor и subagents.
    """

    shared_skills_selection: dict[str, Any] = {}
    return _SkillsMiddlewareBundle(
        supervisor=PreloadedSkillsContextMiddleware(
            skills_root=context.skills_root,
            skills_workspace_dir=context.skills_workspace_dir,
            model=context.model,
            select_skills=True,
            shared_selection=shared_skills_selection,
            prompt_template=SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
        ),
        subagent=PreloadedSkillsContextMiddleware(
            skills_root=context.skills_root,
            skills_workspace_dir=context.skills_workspace_dir,
            model=context.model,
            select_skills=False,
            shared_selection=shared_skills_selection,
            prompt_template=DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
        ),
    )


def _build_subagent_graphs(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    skills_middleware: _SkillsMiddlewareBundle,
) -> list[dict[str, Any]]:
    """Собирает compiled coding-agent и data-retrieval-agent для supervisor.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        skills_middleware: Middleware предзагрузки skills.

    Returns:
        Список subagent-конфигураций для supervisor.
    """

    coding_agent = _build_coding_agent_graph(
        context=context,
        backends=backends,
        tools=tools,
    )
    data_retrieval_agent = _build_data_retrieval_agent_graph(
        context=context,
        backends=backends,
        tools=tools,
        skills_middleware=skills_middleware,
    )
    return [
        {
            "name": CODING_AGENT_NAME,
            "description": CODING_AGENT_DESCRIPTION,
            "runnable": coding_agent,
        },
        {
            "name": DATA_RETRIEVAL_AGENT_NAME,
            "description": DATA_RETRIEVAL_AGENT_DESCRIPTION,
            "runnable": data_retrieval_agent,
        },
    ]


def _build_coding_agent_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
) -> Any:
    """Собирает compiled coding-agent.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.

    Returns:
        Скомпилированный coding-agent.
    """

    middleware = _build_native_runtime_middleware(
        context.settings,
        workspace_root=context.workspace_root,
        agent_name="coding-agent",
        limit_model_calls=True,
        hidden_tool_names=("edit_file",),
    )
    middleware.insert(
        -1,
        MemoryMiddleware(
            backend=backends.coding,
            sources=[context.agents_memory_path],
            add_cache_control=True,
        ),
    )
    return create_deep_agent(
        name=CODING_AGENT_NAME,
        system_prompt=CODING_AGENT_PROMPT,
        model=context.model,
        skills=[context.skills_workspace_dir],
        tools=[
            tools.load_skills_tool,
            tools.python_tool,
            tools.project_structure_tool,
            tools.jupyter_notebook_tool,
        ],
        middleware=middleware,
        backend=backends.coding,
    )


def _build_data_retrieval_agent_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    skills_middleware: _SkillsMiddlewareBundle,
) -> Any:
    """Собирает compiled data-retrieval-agent.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        skills_middleware: Middleware предзагрузки skills.

    Returns:
        Скомпилированный data-retrieval-agent.
    """

    middleware = [
        skills_middleware.subagent,
        *_build_native_runtime_middleware(
            context.settings,
            workspace_root=context.workspace_root,
            agent_name="data-retrieval-agent",
            limit_model_calls=True,
            hidden_tool_names=("edit_file",),
        ),
    ]
    middleware.insert(
        -1,
        MemoryMiddleware(
            backend=backends.data,
            sources=[context.agents_memory_path],
            add_cache_control=True,
        ),
    )
    return create_deep_agent(
        name=DATA_RETRIEVAL_AGENT_NAME,
        system_prompt=DATA_RETRIEVAL_PROMPT,
        model=context.model,
        skills=[context.skills_workspace_dir],
        tools=[
            *tools.data_tools,
            tools.load_skills_tool,
            tools.python_tool,
        ],
        middleware=middleware,
        backend=backends.data,
    )


def _build_supervisor_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    subagents: list[dict[str, Any]],
    skills_middleware: _SkillsMiddlewareBundle,
) -> Any:
    """Собирает финальный DeepAgents supervisor graph.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        subagents: Скомпилированные subagents для supervisor.
        skills_middleware: Middleware предзагрузки skills.

    Returns:
        Скомпилированный supervisor graph.
    """

    runtime_middleware = _build_native_runtime_middleware(
        context.settings,
        workspace_root=context.workspace_root,
        agent_name="supervisor",
        limit_model_calls=False,
        hidden_tool_names=("edit_file",),
    )
    runtime_middleware.insert(
        -1,
        MemoryMiddleware(
            backend=backends.supervisor,
            sources=[
                context.agents_memory_path,
                *(context.user_memory_paths or []),
            ],
            add_cache_control=True,
        ),
    )
    supervisor_system_prompt = SYSTEM_PROMPT
    if context.system_prompt_suffix:
        supervisor_system_prompt = f"{supervisor_system_prompt}\n\n{context.system_prompt_suffix.strip()}"
    return create_deep_agent(
        model=context.model,
        skills=[context.skills_workspace_dir],
        tools=[
            tools.load_skills_tool,
            tools.python_tool,
            tools.project_structure_tool,
            *tools.supervisor_tools,
        ],
        system_prompt=supervisor_system_prompt,
        subagents=subagents,
        backend=backends.supervisor,
        middleware=[
            TodoResetMiddleware(),
            *(
                [AgentRequestLoggingMiddleware(context.request_logger)]
                if context.request_logger is not None
                else []
            ),
            *(
                [
                    UserProfileMemoryMiddleware(
                        profile=context.user_profile_memory,
                        spark_session_factory=context.user_profile_spark_session_factory,
                    )
                ]
                if context.user_profile_memory is not None
                and context.user_profile_spark_session_factory is not None
                else []
            ),
            skills_middleware.supervisor,
            *runtime_middleware,
        ],
        checkpointer=(
            InMemorySaver()
            if context.checkpointer is _DEFAULT_CHECKPOINTER
            else context.checkpointer
        ),
    )



