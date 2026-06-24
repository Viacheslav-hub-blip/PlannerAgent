"""Сборка native DeepAgents агента для аналитики данных и работы с кодом.

Главный файл сборки. Точка входа — :func:`build_analytics_deep_agent`: она собирает
supervisor по нумерованным шагам (settings -> data tools -> middleware -> backend ->
subagents -> custom tools -> ``create_deep_agent``).

Как редактировать/кастомизировать (подробности — в ``README.md``):
- Данные: передай свои ``data_tools=[...]`` в :func:`build_analytics_deep_agent` или укажи
  ``data_tools_factory`` в конфиге (``config/defaults.json`` / override через
  ``DEEP_AGENT_CONFIG_PATH``).
- Конфиг и пороги: ключи в ``config/defaults.json`` (offload, skills, лимиты).
- Поведение supervisor/subagent: правь тематические модули в ``prompts`` без доменной логики.
- Доменные знания: добавляй/редактируй ``skills/<name>/SKILL.md`` — менять код не нужно.
- Новые subagents: добавь отдельный модуль в ``subagents`` и зарегистрируй его в ``registry.py``.

Служебные функции:
- build_data_tools: сборка инструментов чтения данных через фабрику из настроек.
- _load_callable_from_path: импорт callable по строковому пути.
- _normalize_data_tools: проверка и нормализация списка инструментов.
- _normalize_extra_tools: проверка и нормализация дополнительных tools.
- build_analytics_deep_agent: сборка supervisor и subagents.
- build_skills_backend: сборка shell-capable workspace backend для supervisor и coding-agent.
- build_supervisor_backend: сборка filesystem-only backend для data-agent.
- build_conversation_checkpointer: создание памяти текущего диалога LangGraph.
- _normalize_virtual_directory: нормализация state-маршрута текстовых артефактов.
- _resolve_workspace_root: проверка рабочей директории.
- _build_terminal_environment: безопасный набор переменных окружения terminal.
- _build_runtime_context_prompt: формирование runtime-контекста с текущей датой и путями.
- _agents_memory_path: workspace-путь ``AGENTS.md``.
- _require_workspace_path: проверка принадлежности пути workspace.
- create_session_tool_outputs_dir: создание папки tool outputs для одного запуска.
- register_session_tool_outputs_cleanup: регистрация удаления tool outputs при закрытии агента.
- cleanup_session_tool_outputs_dir: удаление папки tool outputs одного запуска.
"""

from __future__ import annotations

import atexit
import importlib
import os
import weakref
from collections.abc import Callable
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent.runtime.harness import register_analytics_harness_profile
from deep_agent.runtime.python_sandbox import build_python_sandbox
from deep_agent.subagents.coding import build_coding_subagent_spec
from deep_agent.subagents.data_retrieval import (
    build_data_retrieval_subagent_spec,
)
from deep_agent.subagents.registry import build_subagent_specs
from deep_agent.runtime.filesystem import (
    Utf8FilesystemBackend,
    Utf8LocalShellBackend,
    configure_read_file_default_limit,
)
from deep_agent.data.result_wrapper import wrap_data_tools_with_query_code
from deep_agent.tools.jupyter_notebook import build_convert_jupyter_notebook_tool
from deep_agent.tools.python_execution import build_python_tool
from deep_agent.tools.project_structure import build_get_project_structure_tool
from deep_agent.tools.skill_loader import build_load_skills_tool
from deep_agent.middleware.skills_context import PreloadedSkillsContextMiddleware
from deep_agent.middleware.filesystem_path_contract import FilesystemPathContractMiddleware
from deep_agent.middleware.gigachat_runtime import (
    LoopBreakerMiddleware,
    ShellSafetyMiddleware,
    ThinkToolMiddleware,
)
from deep_agent.middleware.tool_context_notice import ToolContextNoticeMiddleware
from deep_agent.middleware.tool_descriptions import PromptToolDescriptionsMiddleware
from deep_agent.middleware.todo_reset import TodoResetMiddleware
from deep_agent.logging import build_postgres_logging_middleware
from deep_agent.prompts.gigachat import build_gigachat_practices_prompt
from deep_agent.prompts.tool_contracts import TOOL_DESCRIPTION_OVERRIDES
from deep_agent.prompts.skills import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.supervisor import SYSTEM_PROMPT
from deep_agent.settings import (
    DeepAgentSettings,
    load_deep_agent_settings,
    workspace_tool_root,
    workspace_tool_path,
)
from deep_agent.middleware.tool_output_file import ToolOutputFileMiddleware
from deep_agent.middleware.model_errors import (
    format_model_error,
    is_retryable_model_error,
)

_DEFAULT_CHECKPOINTER = object()


def build_data_tools(settings: DeepAgentSettings | None = None) -> list[BaseTool]:
    """Собирает инструменты чтения данных через фабрику из JSON-конфига."""

    settings = settings or load_deep_agent_settings()
    if not settings.data_tools_factory:
        raise ValueError(
            "Не настроена фабрика tools чтения данных. "
            "Передайте data_tools в build_analytics_deep_agent или укажите "
            "data_tools_factory в deep_agent/config/defaults.json или override-конфиге."
        )
    factory = _load_callable_from_path(settings.data_tools_factory)
    return _normalize_data_tools(factory(**settings.data_tools_factory_kwargs))


def _load_callable_from_path(import_path: str) -> Callable[..., Any]:
    """Импортирует callable по строке вида ``module:attr`` или ``module.attr``."""

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
    """Приводит результат фабрики data-tools к списку ``BaseTool`` с проверкой типов."""

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


def _normalize_extra_tools(raw_tools: Any) -> list[BaseTool]:
    """Приводит дополнительные tools к списку ``BaseTool`` с проверкой типов.

    Args:
        raw_tools: ``None``, один ``BaseTool`` или последовательность ``BaseTool``.

    Returns:
        Нормализованный список дополнительных tools.

    Raises:
        TypeError: Передан объект не ``BaseTool``.
    """

    if raw_tools is None:
        return []
    return _normalize_data_tools(raw_tools)


def build_analytics_deep_agent(
    model: Any,
    settings: DeepAgentSettings | None = None,
    data_tools: list[BaseTool] | None = None,
    extra_tools: list[BaseTool] | None = None,
    workspace_root: str | Path | None = None,
    checkpointer: Any = _DEFAULT_CHECKPOINTER,
    state_artifacts_virtual_dir: str | None = None,
    system_prompt_suffix: str | None = None,
) -> Any:
    """Собирает гибридный аналитический и coding DeepAgent.

    Это главная точка сборки агента. Сборка нативная для DeepAgents: supervisor получает
    встроенные tools (`write_todos`, `task`, filesystem, `execute`), custom tools
    `python`, project memory из ``AGENTS.md`` и два
    специализированных subagents.

    Шаги инициализации (см. нумерацию в теле функции) и точки кастомизации:

    1. Settings — все пороги и пути. Кастомизация: `config/defaults.json`, override-файл
       через env `DEEP_AGENT_CONFIG_PATH`, либо готовый ``settings`` в аргументе.
    2. Data tools — инструменты чтения данных (`load_data`). Кастомизация: передай свои
       ``BaseTool`` в ``data_tools`` или укажи фабрику в ``data_tools_factory`` конфига.
    3. Middleware — project-specific offload больших tool outputs в pickle плюс
       встроенные middleware LangChain/Deep Agents:
       ContextEditingMiddleware (очистка старых tool-результатов при лимите токенов),
       ToolCallLimitMiddleware (общий бюджет вызовов tools),
       ModelRetryMiddleware (повторы ошибок модели),
       нативный ModelCallLimitMiddleware (бюджет ходов одного запуска субагента).
       Кастомизация: пороги в settings; модель выбора skills.
    4. Backend — workspace с terminal, skills и spill-файлами.
    5. Subagents — штатный `general-purpose`, отдельный `coding-agent` для кода
       и `data-retrieval-agent` для таблиц.
    6. Custom tool supervisor — `python` для REPL-расчётов, чтения `.pkl` и артефактов.
    7. Сборка `create_deep_agent(...)` со всеми частями.

    Args:
        model: Chat model LangChain для supervisor и subagent.
        settings: Готовые настройки; если ``None`` — загружаются из JSON-конфига.
        data_tools: Готовые tools чтения данных; если ``None`` — берутся из фабрики конфига.
        extra_tools: Дополнительные tools supervisor, например VLM или MCP tools.
            Они скрыты до загрузки соответствующего skill.
        workspace_root: Рабочая директория coding-agent. Имеет приоритет над settings.
        checkpointer: Checkpointer LangGraph для истории диалога. Если аргумент не передан,
            создаётся штатный ``InMemorySaver``. Явный ``None`` передаёт управление
            persistence внешнему Agent Server.
        state_artifacts_virtual_dir: Виртуальная директория для текстовых артефактов,
            сохраняемых в state LangGraph и доступных UI. Если ``None``, state-маршрут
            не создаётся.
        system_prompt_suffix: Дополнительные инструкции, добавляемые к системному prompt.

    Returns:
        Скомпилированный DeepAgents граф (supervisor), готовый к ``invoke``/``stream``.
    """

    # Шаг 1. Настройки: пути skills, папка spill-файлов, пороги offload, thread_id.
    settings = settings or load_deep_agent_settings()
    configure_read_file_default_limit(settings.read_file_default_limit)
    register_analytics_harness_profile(
        settings.harness_profile_key,
        enable_general_purpose=False,
    )
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    resolved_skills_root = _rebase_workspace_path(
        settings.skills_root,
        settings.workspace_root,
        resolved_workspace_root,
    )
    resolved_tool_outputs_root = _rebase_tool_outputs_path(
        settings.tool_outputs_dir,
        settings.workspace_root,
        resolved_workspace_root,
    )
    session_tool_outputs_dir = create_session_tool_outputs_dir(
        resolved_tool_outputs_root
    )
    skills_workspace_dir = workspace_tool_path(
        resolved_skills_root,
        resolved_workspace_root,
        directory=True,
    )
    agents_memory_path = _agents_memory_path(
        settings.agents_file_name,
        resolved_workspace_root,
    )

    # Шаг 2. Инструменты чтения данных. Аргумент имеет приоритет над фабрикой из конфига.
    # Оборачиваем их в слой прозрачности: агент получает сгенерированный код запроса и
    # счётчики строк, а большие таблицы корректно уходят в offload (artifact с rows).
    if data_tools is None:
        data_tools = build_data_tools(settings)
    data_tools = wrap_data_tools_with_query_code(data_tools)
    extra_tools = _normalize_extra_tools(extra_tools)
    # Шаг 3. Единственный project-specific middleware сохраняет табличные результаты
    # в pickle. Skills, retries, limits, filesystem, memory и subagents собираются
    # штатными middleware LangChain/Deep Agents.
    tool_output_file_middleware = ToolOutputFileMiddleware(
        output_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
        min_rows_to_save=settings.tool_output_min_rows_to_save,
        min_content_chars_to_save=settings.tool_output_min_content_chars_to_save,
        preview_rows=settings.tool_output_preview_rows,
        inline_original_content_chars=settings.tool_output_inline_original_chars,
    )
    data_backend = build_supervisor_backend(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
    )
    supervisor_backend = build_skills_backend(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
        state_artifacts_virtual_dir=state_artifacts_virtual_dir,
    )
    workspace_backend = build_skills_backend(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
    )
    python_sandbox = build_python_sandbox(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
    )
    python_tool = build_python_tool(python_sandbox)
    load_skills_tool = build_load_skills_tool(
        settings,
        skills_root=resolved_skills_root,
        workspace_root=resolved_workspace_root,
    )
    project_structure_tool = build_get_project_structure_tool(
        workspace_root=resolved_workspace_root,
        agent_root=resolved_skills_root.parent,
        skills_root=resolved_skills_root,
    )
    jupyter_notebook_tool = build_convert_jupyter_notebook_tool(
        workspace_root=resolved_workspace_root,
    )
    runtime_context_prompt = _build_runtime_context_prompt(
        resolved_workspace_root,
        session_tool_outputs_dir,
        agent_root=resolved_skills_root.parent,
        skills_root=resolved_skills_root,
        agents_memory_path=agents_memory_path,
    )
    gigachat_practices_prompt = build_gigachat_practices_prompt()
    shared_skills_selection: dict[str, Any] = {}
    supervisor_skills_middleware = PreloadedSkillsContextMiddleware(
        skills_root=resolved_skills_root,
        skills_workspace_dir=skills_workspace_dir,
        model=model,
        select_skills=True,
        shared_selection=shared_skills_selection,
        prompt_template=SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    )
    subagent_skills_middleware = PreloadedSkillsContextMiddleware(
        skills_root=resolved_skills_root,
        skills_workspace_dir=skills_workspace_dir,
        model=model,
        select_skills=False,
        shared_selection=shared_skills_selection,
        prompt_template=DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    )
    coding_agent_middleware = _build_native_runtime_middleware(
        settings,
        tool_output_file_middleware,
        filesystem_backend=workspace_backend,
        workspace_root=resolved_workspace_root,
        agent_name="coding-agent",
        limit_model_calls=True,
    )
    coding_agent_spec = build_coding_subagent_spec(
        model=model,
        tools=[
            load_skills_tool,
            python_tool,
            project_structure_tool,
            jupyter_notebook_tool,
        ],
        common_middleware=coding_agent_middleware,
        skill_sources=[skills_workspace_dir],
    )
    coding_agent_spec["system_prompt"] = (
        f"{coding_agent_spec['system_prompt']}\n\n{gigachat_practices_prompt}\n\n{runtime_context_prompt}"
    )
    coding_agent = create_deep_agent(
        **coding_agent_spec,
        backend=workspace_backend,
        memory=[agents_memory_path],
    )
    data_retrieval_agent_middleware = [
        subagent_skills_middleware,
        *_build_native_runtime_middleware(
            settings,
            tool_output_file_middleware,
            filesystem_backend=data_backend,
            workspace_root=resolved_workspace_root,
            agent_name="data-retrieval-agent",
            limit_model_calls=True,
        ),
    ]
    data_retrieval_agent_spec = build_data_retrieval_subagent_spec(
        model=model,
        data_tools=[
            *data_tools,
            load_skills_tool,
            python_tool,
            project_structure_tool,
        ],
        common_middleware=data_retrieval_agent_middleware,
        skill_sources=[skills_workspace_dir],
    )
    data_retrieval_agent_spec["system_prompt"] = (
        f"{data_retrieval_agent_spec['system_prompt']}\n\n{gigachat_practices_prompt}\n\n{runtime_context_prompt}"
    )
    data_retrieval_agent = create_deep_agent(
        **data_retrieval_agent_spec,
        backend=data_backend,
        memory=[agents_memory_path],
    )

    # Шаг 4. Сборка изолированных compiled subagents.
    subagents = build_subagent_specs(
        coding_agent=coding_agent,
        data_retrieval_agent=data_retrieval_agent,
    )

    # Шаг 6. Финальная сборка DeepAgents supervisor.
    system_prompt = f"{SYSTEM_PROMPT}\n\n{gigachat_practices_prompt}\n\n{runtime_context_prompt}"
    if system_prompt_suffix:
        system_prompt = f"{system_prompt}\n\n{system_prompt_suffix.strip()}"

    register_analytics_harness_profile(
        settings.harness_profile_key,
        enable_general_purpose=True,
    )
    agent = create_deep_agent(
        model=model,
        tools=[load_skills_tool, python_tool, project_structure_tool, *extra_tools],
        system_prompt=system_prompt,
        subagents=subagents,
        skills=[skills_workspace_dir],
        backend=supervisor_backend,
        middleware=[
            TodoResetMiddleware(),
            supervisor_skills_middleware,
            *_build_native_runtime_middleware(
                settings,
                tool_output_file_middleware,
                filesystem_backend=supervisor_backend,
                workspace_root=resolved_workspace_root,
                agent_name="supervisor",
                limit_model_calls=False,
            ),
        ],
        memory=[agents_memory_path],
        checkpointer=(
            build_conversation_checkpointer()
            if checkpointer is _DEFAULT_CHECKPOINTER
            else checkpointer
        ),
    )
    return agent


def _build_native_runtime_middleware(
    settings: DeepAgentSettings,
    tool_output_file_middleware: ToolOutputFileMiddleware,
    *,
    filesystem_backend: Any | None = None,
    workspace_root: Path | None = None,
    agent_name: str = "supervisor",
    limit_model_calls: bool,
) -> list[Any]:
    """Собирает runtime middleware из публичных реализаций LangChain.

    Args:
        settings: Настройки лимитов и управления контекстом.
        tool_output_file_middleware: Единственный project-specific middleware.
        filesystem_backend: Backend filesystem tools для нормализации путей и проверки записи.
        workspace_root: Корень workspace для canonical POSIX-путей filesystem tools.
        agent_name: Имя агента для служебного логирования.
        limit_model_calls: Нужно ли ограничивать число model calls для subagent.

    Returns:
        Список middleware для передачи в ``create_deep_agent``.
    """

    postgres_logging_middleware = build_postgres_logging_middleware(
        agent_name=agent_name
    )
    middleware: list[Any] = [
        PromptToolDescriptionsMiddleware(TOOL_DESCRIPTION_OVERRIDES),
        ThinkToolMiddleware(),
        ShellSafetyMiddleware(),
        LoopBreakerMiddleware(),
        ModelRetryMiddleware(
            max_retries=settings.max_model_retries,
            retry_on=is_retryable_model_error,
            on_failure=format_model_error,
        ),
        tool_output_file_middleware,
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=settings.context_edit_trigger_tokens,
                    keep=settings.context_edit_keep_tool_results,
                )
            ]
        ),
        ToolCallLimitMiddleware(
            run_limit=settings.max_tool_calls_per_run,
            exit_behavior="continue",
        ),
    ]
    if filesystem_backend is not None and workspace_root is not None:
        middleware.insert(
            3,
            FilesystemPathContractMiddleware(
                workspace_root=workspace_root.resolve(),
                backend=filesystem_backend,
            ),
        )
    middleware.append(ToolContextNoticeMiddleware())
    if postgres_logging_middleware is not None:
        middleware.insert(3, postgres_logging_middleware)
    if limit_model_calls:
        middleware.append(
            ModelCallLimitMiddleware(
                run_limit=settings.max_subagent_model_calls,
                exit_behavior="end",
            )
        )
    return middleware


def build_skills_backend(
    settings: DeepAgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает backend coding-agent с единым файловым корнем workspace.

    Args:
        settings: Настройки агента; если ``None`` — загружаются из JSON-конфига.
        tool_outputs_dir: Папка tool outputs текущего запуска; может находиться
            внутри workspace или быть внешним абсолютным путём.
        workspace_root: Корень доступного агенту workspace.
        state_artifacts_virtual_dir: Виртуальная директория, направляемая в ``StateBackend``
            для отображения текстовых артефактов в LangGraph UI.

    Returns:
        ``CompositeBackend`` с terminal и полным файловым доступом внутри workspace.
    """

    settings = settings or load_deep_agent_settings()
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    resolved_tool_outputs_dir = tool_outputs_dir or _rebase_tool_outputs_path(
        settings.tool_outputs_dir,
        settings.workspace_root,
        resolved_workspace_root,
    )
    routes: dict[str, Any] = {}
    artifacts_root = "/"
    if state_artifacts_virtual_dir:
        artifacts_root = _normalize_virtual_directory(state_artifacts_virtual_dir)
        routes[artifacts_root] = StateBackend()

    return CompositeBackend(
        default=Utf8LocalShellBackend(
            root_dir=resolved_workspace_root,
            virtual_mode=True,
            timeout=settings.terminal_timeout,
            max_output_bytes=settings.terminal_max_output_bytes,
            env=_build_terminal_environment(),
            inherit_env=False,
        ),
        routes=routes,
        artifacts_root=artifacts_root,
    )


def build_supervisor_backend(
    settings: DeepAgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает filesystem-only backend для data-agent с полным доступом к workspace.

    Args:
        settings: Настройки агента; если ``None``, загружаются defaults.
        tool_outputs_dir: Папка pickle-результатов внутри workspace или внешний
            абсолютный путь.
        workspace_root: Единый корень доступного файлового пространства.
        state_artifacts_virtual_dir: Виртуальная директория UI-артефактов.

    Returns:
        ``CompositeBackend`` без shell, но с чтением и записью всех папок workspace.
    """

    settings = settings or load_deep_agent_settings()
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    resolved_tool_outputs_dir = tool_outputs_dir or _rebase_tool_outputs_path(
        settings.tool_outputs_dir,
        settings.workspace_root,
        resolved_workspace_root,
    )
    routes: dict[str, Any] = {}
    artifacts_root = "/"
    if state_artifacts_virtual_dir:
        artifacts_root = _normalize_virtual_directory(state_artifacts_virtual_dir)
        routes[artifacts_root] = StateBackend()

    return CompositeBackend(
        default=Utf8FilesystemBackend(
            root_dir=resolved_workspace_root,
            virtual_mode=True,
        ),
        routes=routes,
        artifacts_root=artifacts_root,
    )


def _normalize_virtual_directory(value: str) -> str:
    """Нормализует виртуальную директорию backend к виду ``/name/``.

    Args:
        value: Пользовательский виртуальный путь.

    Returns:
        Абсолютный POSIX-путь с завершающим слешем.

    Raises:
        ValueError: Путь пустой или указывает на корень.
    """

    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("Виртуальная директория артефактов не может быть пустой или корневой.")
    return f"/{normalized}/"


def build_conversation_checkpointer() -> InMemorySaver:
    """Создаёт штатную краткосрочную память LangGraph для диалога.

    Returns:
        ``InMemorySaver``, сохраняющий сообщения и state между вызовами с одинаковым
        ``thread_id`` в пределах процесса.
    """

    return InMemorySaver()


def _resolve_workspace_root(value: str | Path) -> Path:
    """Проверяет и возвращает абсолютный путь рабочего workspace.

    Args:
        value: Путь из settings или аргумента builder.

    Returns:
        Абсолютный существующий путь директории.

    Raises:
        ValueError: Путь не существует или не является директорией.
    """

    resolved = Path(value).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"Workspace не существует: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Workspace должен быть директорией: {resolved}")
    return resolved


def _rebase_workspace_path(
    path: Path,
    source_workspace_root: Path,
    target_workspace_root: Path,
) -> Path:
    """Переносит настроенный workspace-путь на runtime workspace с тем же относительным именем.

    Args:
        path: Абсолютный путь из настроек.
        source_workspace_root: ``workspace_root``, относительно которого загружены настройки.
        target_workspace_root: Фактический workspace текущей сборки агента.

    Returns:
        Абсолютный путь внутри ``target_workspace_root``.

    Raises:
        ValueError: Исходный путь находится вне настроенного workspace.
    """

    source_root = source_workspace_root.resolve()
    try:
        relative_path = path.resolve().relative_to(source_root)
    except ValueError:
        raise ValueError(
            f"Configured path must be inside workspace_root: {path.resolve()}"
        ) from None
    return (target_workspace_root / relative_path).resolve()


def _rebase_tool_outputs_path(
    path: Path,
    source_workspace_root: Path,
    target_workspace_root: Path,
) -> Path:
    """Переносит workspace-relative tool outputs или оставляет внешний абсолютный путь.

    Args:
        path: Абсолютный путь из настроек.
        source_workspace_root: ``workspace_root``, относительно которого загружены настройки.
        target_workspace_root: Фактический workspace текущей сборки агента.

    Returns:
        Путь внутри ``target_workspace_root`` для workspace-relative настроек или
        исходный абсолютный путь для внешних каталогов вроде ``/runs/...``.
    """

    source_root = source_workspace_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(source_root)
    except ValueError:
        return resolved_path
    return (target_workspace_root / relative_path).resolve()


def _require_workspace_path(path: Path, workspace_root: Path) -> Path:
    """Проверяет, что путь находится внутри workspace, и возвращает его абсолютный вид.

    Args:
        path: Проверяемый путь.
        workspace_root: Разрешённый корень файловой системы агента.

    Returns:
        Абсолютный путь внутри workspace.

    Raises:
        ValueError: Путь выходит за пределы workspace.
    """

    resolved = path.resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError:
        raise ValueError(f"Path must be inside workspace_root: {resolved}") from None
    return resolved


def _build_terminal_environment() -> dict[str, str]:
    """Возвращает системные переменные без API-ключей и пользовательских секретов.

    Returns:
        Минимальный environment для локальных команд Windows/POSIX.
    """

    allowed_names = (
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PYTHONIOENCODING",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    )
    return {name: os.environ[name] for name in allowed_names if name in os.environ}


def _build_runtime_context_prompt(
    workspace_root: Path,
    tool_outputs_dir: Path,
    *,
    agent_root: Path | None = None,
    skills_root: Path | None = None,
    agents_memory_path: str | None = None,
) -> str:
    """Формирует runtime-блок для system prompt с датой запуска и путями.

    Args:
        workspace_root: Реальный корень workspace текущего запуска.
        tool_outputs_dir: Реальный каталог session tool outputs.
        agent_root: Реальная папка реализации агента внутри workspace.
        skills_root: Реальная папка skills внутри workspace.
        agents_memory_path: Workspace-путь к файлу project memory.

    Returns:
        XML-подобный блок system prompt с текущей датой, корнем workspace и правилами
        интерпретации относительных дат.
    """

    today = date.today().isoformat()
    try:
        workspace_outputs_path = workspace_tool_path(
            tool_outputs_dir,
            workspace_root,
            directory=True,
        )
    except ValueError:
        workspace_outputs_path = str(tool_outputs_dir.resolve())
    agent_root_line = ""
    if agent_root is not None:
        agent_root_line = (
            "\nAgent implementation directory: "
            f"{workspace_tool_path(agent_root, workspace_root, directory=True)} maps to real path {agent_root.resolve()}."
        )
    skills_root_line = ""
    if skills_root is not None:
        skills_root_line = (
            "\nSkills directory: "
            f"{workspace_tool_path(skills_root, workspace_root, directory=True)} maps to real path {skills_root.resolve()}."
        )
    memory_path_line = ""
    if agents_memory_path:
        memory_path_line = f"\nProject memory file: {agents_memory_path}."
    return f"""
<runtime_context>
## Runtime Context

Current date: {today}.
Workspace root: {workspace_tool_root(workspace_root)} maps to real path {workspace_root.resolve()}.
Data artifacts directory: {workspace_outputs_path} maps to real path {tool_outputs_dir.resolve()}.
{agent_root_line}{skills_root_line}{memory_path_line}

For relative dates in user requests, calculate the period from Current date. For example, "last 2 days" means the
two calendar days ending on Current date unless the user explicitly defines another business convention. Never take
relative dates from examples, validation cases, demo data, or visible table partitions.

Use `/artifacts` only for `load_data` offload files, data exports, and intermediate transformation outputs. Do not
move ordinary user files, source code, documentation, reports, notebooks, or requested repository files into
`/artifacts` unless the user explicitly names that path. For regular file creation, use the user's requested path or
an appropriate workspace path under `/`. When reporting saved data artifacts, include their workspace path.

Use the Agent implementation directory and Skills directory from this runtime context. Do not assume that agent code or
skills live at `/deep_agent/` when the runtime context shows another path.
</runtime_context>
""".strip()


def _agents_memory_path(file_name: str, workspace_root: str | Path) -> str:
    """Преобразует имя project memory в абсолютный виртуальный путь.

    Args:
        file_name: Имя или относительный путь ``AGENTS.md`` в workspace.
        workspace_root: Корень workspace для построения полного tool-пути.

    Returns:
        POSIX-путь, подходящий для ``create_deep_agent(memory=...)``.

    Raises:
        ValueError: Путь пытается выйти за пределы workspace.
    """

    normalized = str(file_name or "AGENTS.md").strip().replace("\\", "/").lstrip("/")
    normalized = normalized or "AGENTS.md"
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError("Путь AGENTS.md не должен выходить за пределы workspace.")
    root = Path(workspace_root).resolve()
    return workspace_tool_path(root.joinpath(*PurePosixPath(normalized).parts), root)


def create_session_tool_outputs_dir(base_dir: Path) -> Path:
    """Создаёт единый каталог tool outputs для артефактов агента.

    Args:
        base_dir: Базовая директория артефактов.

    Returns:
        Абсолютный путь к единому каталогу артефактов.
    """

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir.resolve()


def register_session_tool_outputs_cleanup(agent: Any, session_dir: Path) -> None:
    """Регистрирует удаление pickle-файлов текущего запуска при уничтожении агента.

    Args:
        agent: Собранный граф агента, жизненный цикл которого ограничивает session.
        session_dir: Папка tool outputs текущего запуска.

    Returns:
        ``None``. Очистка выполняется через ``weakref.finalize`` при сборке мусора или
        завершении процесса Python.
    """

    try:
        weakref.finalize(agent, cleanup_session_tool_outputs_dir, session_dir)
    except TypeError:
        atexit.register(cleanup_session_tool_outputs_dir, session_dir)


def cleanup_session_tool_outputs_dir(session_dir: Path) -> None:
    """Сохраняет единый каталог артефактов и ничего не удаляет.

    Args:
        session_dir: Единый каталог артефактов.

    Returns:
        ``None``. Каталог артефактов является пользовательским результатом и не очищается автоматически.
    """

    return None


__all__ = [
    "build_analytics_deep_agent",
    "build_conversation_checkpointer",
    "build_data_tools",
    "build_skills_backend",
    "build_supervisor_backend",
    "cleanup_session_tool_outputs_dir",
    "create_session_tool_outputs_dir",
    "register_session_tool_outputs_cleanup",
]
