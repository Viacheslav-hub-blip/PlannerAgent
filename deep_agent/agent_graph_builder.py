"""Этапы сборки DeepAgent graph.

Содержит функции и классы:
- _AgentBuildContext: контейнер настроек и путей одного запуска.
- _AgentBackends: контейнер backend-ов graph.
- _AgentTools: контейнер tools graph.
- _AgentPromptBundle: контейнер prompt-блоков graph.
- _SkillsMiddlewareBundle: контейнер skills middleware.
- _build_agent_context: подготовка настроек, модели и путей.
- _build_tool_output_file_middleware: сборка middleware сохранения outputs.
- _build_agent_backends: сборка backend-ов.
- _build_agent_tools: сборка tools.
- _build_agent_prompts: сборка prompt-блоков.
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
from langchain_core.tools import BaseTool

from deep_agent.agent_settings import AgentSettings, load_agent_settings, workspace_tool_path
from deep_agent.execution.python_sandbox import build_python_sandbox
from deep_agent.middleware.skills_context_middleware import PreloadedSkillsContextMiddleware
from deep_agent.middleware.request_logging_middleware import (
    AgentRequestLogger,
    AgentRequestLoggingMiddleware,
)
from deep_agent.middleware.todo_reset_middleware import TodoResetMiddleware
from deep_agent.middleware.tool_output_file_middleware import ToolOutputFileMiddleware
from deep_agent.middleware.user_profile_memory_middleware import UserProfileMemoryMiddleware
from deep_agent.prompts.skills_context_prompt import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.supervisor_prompt import SYSTEM_PROMPT
from deep_agent.subagents import (
    build_coding_subagent_config,
    build_data_retrieval_subagent_config,
    build_supervisor_subagent_configs,
)
from deep_agent.tools.jupyter_notebook_tool import build_convert_jupyter_notebook_tool
from deep_agent.tools.python_execution_tool import build_python_tool
from deep_agent.tools.project_structure_tool import build_get_project_structure_tool
from deep_agent.tools.refactor_review_tool import build_review_refactor_tool
from deep_agent.tools.skill_loader_tool import build_load_skills_tool
from deep_agent.agent import (
    _DEFAULT_CHECKPOINTER,
    _agents_memory_path,
    _build_native_runtime_middleware,
    _rebase_tool_outputs_path,
    _rebase_workspace_path,
    _resolve_workspace_root,
    build_conversation_checkpointer,
    build_skills_backend,
    build_supervisor_backend,
    create_session_tool_outputs_dir,
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
        user_memory_store: Store с долговременной памятью пользователя или ``None``.
        user_memory_namespace: Namespace памяти пользователя или ``None``.
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
    user_memory_store: Any | None
    user_memory_namespace: tuple[str, ...] | None
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
        review_refactor_tool: Инструмент локального ревью refactor.

    Returns:
        Контейнер tools для helper-функций сборки.
    """

    data_tools: list[BaseTool]
    supervisor_tools: list[BaseTool]
    python_tool: Any
    load_skills_tool: Any
    project_structure_tool: Any
    jupyter_notebook_tool: Any
    review_refactor_tool: Any


@dataclass(frozen=True)
class _AgentPromptBundle:
    """Хранит итоговый prompt главного агента.

    Args:
        supervisor_system_prompt: Итоговый системный prompt supervisor.

    Returns:
        Контейнер prompt-текста для сборки graph.
    """

    supervisor_system_prompt: str


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
    user_memory_store: Any | None = None,
    user_memory_namespace: tuple[str, ...] | None = None,
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
        user_memory_store: Store с долговременной памятью пользователя или ``None``.
        user_memory_namespace: Namespace памяти пользователя или ``None``.
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
    tool_outputs_dir = create_session_tool_outputs_dir(resolved_tool_outputs_root)
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
        user_memory_store=user_memory_store,
        user_memory_namespace=user_memory_namespace,
        user_memory_paths=user_memory_paths,
    )


def _build_tool_output_file_middleware(context: _AgentBuildContext) -> ToolOutputFileMiddleware:
    """Создает middleware сохранения крупных tool outputs в файлы.

    Args:
        context: Контекст сборки агента.

    Returns:
        Настроенный ``ToolOutputFileMiddleware``.
    """

    settings = context.settings
    return ToolOutputFileMiddleware(
        output_dir=context.tool_outputs_dir,
        workspace_root=context.workspace_root,
        min_rows_to_save=settings.tool_output_min_rows_to_save,
        min_content_chars_to_save=settings.tool_output_min_content_chars_to_save,
        preview_rows=settings.tool_output_preview_rows,
        inline_original_content_chars=settings.tool_output_inline_original_chars,
    )


def _build_agent_backends(context: _AgentBuildContext) -> _AgentBackends:
    """Собирает backend-ы для supervisor, coding-agent и data-retrieval-agent.

    Args:
        context: Контекст сборки агента.

    Returns:
        Контейнер backend-ов по зонам ответственности.
    """

    return _AgentBackends(
        data=build_supervisor_backend(
            context.settings,
            tool_outputs_dir=context.tool_outputs_dir,
            workspace_root=context.workspace_root,
        ),
        supervisor=build_skills_backend(
            context.settings,
            tool_outputs_dir=context.tool_outputs_dir,
            workspace_root=context.workspace_root,
            state_artifacts_virtual_dir=context.state_artifacts_virtual_dir,
            memory_namespace=context.user_memory_namespace,
        ),
        coding=build_skills_backend(
            context.settings,
            tool_outputs_dir=context.tool_outputs_dir,
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
        python_tool=build_python_tool(python_sandbox),
        load_skills_tool=build_load_skills_tool(
            context.settings,
            skills_root=context.skills_root,
            workspace_root=context.workspace_root,
        ),
        project_structure_tool=build_get_project_structure_tool(
            workspace_root=context.workspace_root,
            agent_root=context.skills_root.parent,
            skills_root=context.skills_root,
        ),
        jupyter_notebook_tool=build_convert_jupyter_notebook_tool(
            workspace_root=context.workspace_root,
        ),
        review_refactor_tool=build_review_refactor_tool(
            model=context.model,
            workspace_root=context.workspace_root,
        ),
    )


def _build_agent_prompts(context: _AgentBuildContext) -> _AgentPromptBundle:
    """Собирает итоговый prompt для supervisor.

    Args:
        context: Контекст сборки агента.

    Returns:
        Контейнер supervisor prompt.
    """

    supervisor_system_prompt = SYSTEM_PROMPT
    if context.system_prompt_suffix:
        supervisor_system_prompt = f"{supervisor_system_prompt}\n\n{context.system_prompt_suffix.strip()}"
    return _AgentPromptBundle(
        supervisor_system_prompt=supervisor_system_prompt,
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
    tool_output_file_middleware: ToolOutputFileMiddleware,
) -> list[dict[str, Any]]:
    """Собирает compiled coding-agent и data-retrieval-agent для supervisor.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        skills_middleware: Middleware предзагрузки skills.
        tool_output_file_middleware: Middleware сохранения крупных outputs.

    Returns:
        Список subagent-конфигураций для supervisor.
    """

    coding_agent = _build_coding_agent_graph(
        context=context,
        backends=backends,
        tools=tools,
        tool_output_file_middleware=tool_output_file_middleware,
    )
    data_retrieval_agent = _build_data_retrieval_agent_graph(
        context=context,
        backends=backends,
        tools=tools,
        skills_middleware=skills_middleware,
        tool_output_file_middleware=tool_output_file_middleware,
    )
    return build_supervisor_subagent_configs(
        coding_agent=coding_agent,
        data_retrieval_agent=data_retrieval_agent,
    )


def _build_coding_agent_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    tool_output_file_middleware: ToolOutputFileMiddleware,
) -> Any:
    """Собирает compiled coding-agent.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        tool_output_file_middleware: Middleware сохранения крупных outputs.

    Returns:
        Скомпилированный coding-agent.
    """

    middleware = _build_native_runtime_middleware(
        context.settings,
        tool_output_file_middleware,
        filesystem_backend=backends.coding,
        workspace_root=context.workspace_root,
        agent_name="coding-agent",
        limit_model_calls=True,
        hidden_tool_names=("edit_file",),
    )
    config = build_coding_subagent_config(
        model=context.model,
        tools=[
            tools.load_skills_tool,
            tools.python_tool,
            tools.project_structure_tool,
            tools.jupyter_notebook_tool,
            tools.review_refactor_tool,
        ],
        common_middleware=middleware,
        skill_sources=[context.skills_workspace_dir],
    )
    return create_deep_agent(
        **config,
        backend=backends.coding,
        memory=[context.agents_memory_path],
    )


def _build_data_retrieval_agent_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    skills_middleware: _SkillsMiddlewareBundle,
    tool_output_file_middleware: ToolOutputFileMiddleware,
) -> Any:
    """Собирает compiled data-retrieval-agent.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        skills_middleware: Middleware предзагрузки skills.
        tool_output_file_middleware: Middleware сохранения крупных outputs.

    Returns:
        Скомпилированный data-retrieval-agent.
    """

    middleware = [
        skills_middleware.subagent,
        *_build_native_runtime_middleware(
            context.settings,
            tool_output_file_middleware,
            filesystem_backend=backends.data,
            workspace_root=context.workspace_root,
            agent_name="data-retrieval-agent",
            limit_model_calls=True,
            hidden_tool_names=("get_project_structure", "edit_file"),
        ),
    ]
    config = build_data_retrieval_subagent_config(
        model=context.model,
        data_tools=[
            *tools.data_tools,
            tools.load_skills_tool,
            tools.python_tool,
        ],
        common_middleware=middleware,
        skill_sources=[context.skills_workspace_dir],
    )
    return create_deep_agent(
        **config,
        backend=backends.data,
        memory=[context.agents_memory_path],
    )


def _build_supervisor_graph(
    *,
    context: _AgentBuildContext,
    backends: _AgentBackends,
    tools: _AgentTools,
    prompts: _AgentPromptBundle,
    subagents: list[dict[str, Any]],
    skills_middleware: _SkillsMiddlewareBundle,
    tool_output_file_middleware: ToolOutputFileMiddleware,
) -> Any:
    """Собирает финальный DeepAgents supervisor graph.

    Args:
        context: Контекст сборки агента.
        backends: Backend-ы graph.
        tools: Общие tools.
        prompts: Общие prompt-блоки.
        subagents: Скомпилированные subagents для supervisor.
        skills_middleware: Middleware предзагрузки skills.
        tool_output_file_middleware: Middleware сохранения крупных outputs.

    Returns:
        Скомпилированный supervisor graph.
    """

    return create_deep_agent(
        model=context.model,
        tools=[
            tools.load_skills_tool,
            tools.python_tool,
            tools.project_structure_tool,
            *tools.supervisor_tools,
        ],
        system_prompt=prompts.supervisor_system_prompt,
        subagents=subagents,
        skills=[context.skills_workspace_dir],
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
            *_build_native_runtime_middleware(
                context.settings,
                tool_output_file_middleware,
                filesystem_backend=backends.supervisor,
                workspace_root=context.workspace_root,
                agent_name="supervisor",
                limit_model_calls=False,
                hidden_tool_names=("edit_file",),
            ),
        ],
        memory=[
            context.agents_memory_path,
            *(context.user_memory_paths or []),
        ],
        checkpointer=(
            build_conversation_checkpointer()
            if context.checkpointer is _DEFAULT_CHECKPOINTER
            else context.checkpointer
        ),
        store=context.user_memory_store,
    )



