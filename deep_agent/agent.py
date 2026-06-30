"""Сборка native DeepAgents агента для аналитики данных и работы с кодом.

Главный файл сборки. Точка входа — :func:`build_agent`: она собирает
supervisor по нумерованным шагам (settings -> data tools -> middleware -> backend ->
subagents -> custom tools -> ``create_deep_agent``).

Как редактировать/кастомизировать (подробности — в ``README.md``):
- Данные: передай свои ``data_tools=[...]`` в :func:`build_agent`.
- Конфиг и пороги: Python-defaults в ``agent_settings.py``.
- Поведение supervisor/subagent: правь тематические модули в ``prompts`` без доменной логики.
- Доменные знания: добавляй/редактируй корневые ``skills/<name>/SKILL.md`` — менять код не нужно.
- Новые subagents: добавь конфигурацию в ``subagents.py``.

Служебные функции:
- build_agent: сборка supervisor и subagents.
- _normalize_data_tools: проверка и нормализация списка инструментов.
- build_skills_backend: сборка shell-capable workspace backend для supervisor и coding-agent.
- build_supervisor_backend: сборка filesystem-only backend для data-agent.
- build_conversation_checkpointer: создание памяти текущего диалога LangGraph.
- _normalize_virtual_directory: нормализация state-маршрута текстовых артефактов.
- _resolve_workspace_root: проверка рабочей директории.
- _build_terminal_environment: безопасный набор переменных окружения terminal.
- _build_runtime_context_prompt: формирование runtime-контекста с текущей датой и путями.
- _agents_memory_path: workspace-путь ``AGENTS.md``.
- create_session_tool_outputs_dir: создание папки tool outputs для одного запуска.
- cleanup_session_tool_outputs_dir: удаление папки tool outputs одного запуска.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

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

from deep_agent.execution.filesystem_backend import (
    Utf8FilesystemBackend,
    Utf8LocalShellBackend,
)
from deep_agent.data_processing.load_data_result import wrap_data_tools_with_query_code
from deep_agent.middleware.filesystem_path_middleware import FilesystemPathContractMiddleware
from deep_agent.middleware.gigachat_runtime_middleware import (
    LoopBreakerMiddleware,
    ShellSafetyMiddleware,
    ThinkToolMiddleware,
)
from deep_agent.middleware.tool_context_middleware import ToolContextNoticeMiddleware
from deep_agent.middleware.tool_description_middleware import (
    PromptToolDescriptionsMiddleware,
    PromptToolFilterMiddleware,
)
from deep_agent.middleware.todo_reset_middleware import TodoResetMiddleware
from deep_agent.prompts.gigachat_runtime_prompt import (
    build_runtime_context_prompt,
)
from deep_agent.prompts.tool_description_prompt import TOOL_DESCRIPTION_OVERRIDES
from deep_agent.agent_settings import (
    AgentSettings,
    load_agent_settings,
    workspace_tool_root,
    workspace_tool_path,
)
from deep_agent.middleware.tool_output_file_middleware import ToolOutputFileMiddleware
from deep_agent.middleware.model_error_middleware import (
    format_model_error,
    is_retryable_model_error,
)

_DEFAULT_CHECKPOINTER = object()


def _normalize_data_tools(raw_tools: Any) -> list[BaseTool]:
    """Приводит явно переданные data-tools к списку ``BaseTool`` с проверкой типов."""

    if isinstance(raw_tools, BaseTool):
        return [raw_tools]
    if not isinstance(raw_tools, (list, tuple)):
        raise TypeError("data_tools должен быть BaseTool или списком BaseTool.")

    tools: list[BaseTool] = []
    for item in raw_tools:
        if not isinstance(item, BaseTool):
            raise TypeError(f"data_tools содержит объект не BaseTool: {type(item).__name__}")
        tools.append(item)
    return tools


def build_agent(
    *,
    model: Any | None = None,
    settings: AgentSettings | None = None,
    data_tools: list[BaseTool] | BaseTool,
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

    1. Settings — все пороги и пути из ``agent_settings.py`` или готового ``settings``.
    2. Data tools — явно переданные инструменты чтения данных (`load_data`).
    3. Middleware — project-specific offload больших tool outputs в pickle плюс
       встроенные middleware LangChain/Deep Agents:
       ContextEditingMiddleware (очистка старых tool-результатов при лимите токенов),
       ToolCallLimitMiddleware (общий бюджет вызовов tools),
       ModelRetryMiddleware (повторы ошибок модели),
       нативный ModelCallLimitMiddleware (бюджет ходов одного запуска субагента).
       Кастомизация: пороги в settings; модель выбора skills.
    4. Backend — workspace с terminal, skills и spill-файлами.
    5. Subagents — отдельный `coding-agent` для кода и `data-retrieval-agent` для таблиц.
    6. Custom tool supervisor — `python` для REPL-расчётов, чтения `.pkl` и артефактов.
    7. Сборка `create_deep_agent(...)` со всеми частями.

    Args:
        model: Chat model LangChain для supervisor и subagent. Если ``None``, создаётся
            Gigachat KitAI модель.
        settings: Готовые настройки; если ``None`` — используются Python-defaults.
        data_tools: Готовые tools чтения данных.
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

    from deep_agent.agent_graph_builder import (
        _build_agent_backends,
        _build_agent_context,
        _build_agent_prompts,
        _build_agent_tools,
        _build_skills_middleware,
        _build_subagent_graphs,
        _build_supervisor_graph,
        _build_tool_output_file_middleware,
    )

    context = _build_agent_context(
        model=model,
        settings=settings,
        workspace_root=workspace_root,
        checkpointer=checkpointer,
        state_artifacts_virtual_dir=state_artifacts_virtual_dir,
        system_prompt_suffix=system_prompt_suffix,
    )
    normalized_data_tools = wrap_data_tools_with_query_code(_normalize_data_tools(data_tools))
    tool_output_file_middleware = _build_tool_output_file_middleware(context)
    backends = _build_agent_backends(context)
    tools = _build_agent_tools(context, data_tools=normalized_data_tools)
    prompts = _build_agent_prompts(context)
    skills_middleware = _build_skills_middleware(context)
    subagents = _build_subagent_graphs(
        context=context,
        backends=backends,
        tools=tools,
        prompts=prompts,
        skills_middleware=skills_middleware,
        tool_output_file_middleware=tool_output_file_middleware,
    )
    return _build_supervisor_graph(
        context=context,
        backends=backends,
        tools=tools,
        prompts=prompts,
        subagents=subagents,
        skills_middleware=skills_middleware,
        tool_output_file_middleware=tool_output_file_middleware,
    )


def _build_native_runtime_middleware(
    settings: AgentSettings,
    tool_output_file_middleware: ToolOutputFileMiddleware,
    *,
    filesystem_backend: Any | None = None,
    workspace_root: Path | None = None,
    agent_name: str = "supervisor",
    limit_model_calls: bool,
    hidden_tool_names: tuple[str, ...] = (),
) -> list[Any]:
    """Собирает runtime middleware из публичных реализаций LangChain.

    Args:
        settings: Настройки лимитов и управления контекстом.
        tool_output_file_middleware: Единственный project-specific middleware.
        filesystem_backend: Backend filesystem tools для нормализации путей и проверки записи.
        workspace_root: Корень workspace для canonical POSIX-путей filesystem tools.
        agent_name: Имя агента для служебного логирования.
        limit_model_calls: Нужно ли ограничивать число model calls для subagent.
        hidden_tool_names: Имена tools, которые нужно скрыть от модели для этого агента.

    Returns:
        Список middleware для передачи в ``create_deep_agent``.
    """

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
    if hidden_tool_names:
        middleware.insert(1, PromptToolFilterMiddleware(tuple(hidden_tool_names)))
    if filesystem_backend is not None and workspace_root is not None:
        middleware.insert(
            3,
            FilesystemPathContractMiddleware(
                workspace_root=workspace_root.resolve(),
                backend=filesystem_backend,
            ),
    )
    middleware.append(ToolContextNoticeMiddleware())
    if limit_model_calls:
        middleware.append(
            ModelCallLimitMiddleware(
                run_limit=settings.max_subagent_model_calls,
                exit_behavior="end",
            )
        )
    return middleware


def build_skills_backend(
    settings: AgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает backend coding-agent с единым файловым корнем workspace.

    Args:
        settings: Настройки агента; если ``None`` — используются Python-defaults.
        tool_outputs_dir: Папка tool outputs текущего запуска; может находиться
            внутри workspace или быть внешним абсолютным путём.
        workspace_root: Корень доступного агенту workspace.
        state_artifacts_virtual_dir: Виртуальная директория, направляемая в ``StateBackend``
            для отображения текстовых артефактов в LangGraph UI.

    Returns:
        ``CompositeBackend`` с terminal и полным файловым доступом внутри workspace.
    """

    settings = settings or load_agent_settings(workspace_root)
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
    settings: AgentSettings | None = None,
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

    settings = settings or load_agent_settings(workspace_root)
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
        исходный абсолютный путь для внешних каталогов вроде ``/artifacts/...``.
    """

    source_root = source_workspace_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(source_root)
    except ValueError:
        return resolved_path
    return (target_workspace_root / relative_path).resolve()


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
            "\nДиректория реализации агента: "
            f"{workspace_tool_path(agent_root, workspace_root, directory=True)} соответствует реальному пути {agent_root.resolve()}."
        )
    skills_root_line = ""
    if skills_root is not None:
        skills_root_line = (
            "\nДиректория skills: "
            f"{workspace_tool_path(skills_root, workspace_root, directory=True)} соответствует реальному пути {skills_root.resolve()}."
        )
    memory_path_line = ""
    if agents_memory_path:
        memory_path_line = f"\nФайл project memory: {agents_memory_path}."
    return build_runtime_context_prompt(
        current_date=today,
        workspace_tool_root_path=workspace_tool_root(workspace_root),
        workspace_real_path=str(workspace_root.resolve()),
        data_artifacts_tool_path=workspace_outputs_path,
        data_artifacts_real_path=str(tool_outputs_dir.resolve()),
        agent_root_line=agent_root_line,
        skills_root_line=skills_root_line,
        memory_path_line=memory_path_line,
    )


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


def cleanup_session_tool_outputs_dir(session_dir: Path) -> None:
    """Сохраняет единый каталог артефактов и ничего не удаляет.

    Args:
        session_dir: Единый каталог артефактов.

    Returns:
        ``None``. Каталог артефактов является пользовательским результатом и не очищается автоматически.
    """

    return None


__all__ = [
    "build_agent",
    "build_conversation_checkpointer",
    "build_skills_backend",
    "build_supervisor_backend",
    "cleanup_session_tool_outputs_dir",
    "create_session_tool_outputs_dir",
]


