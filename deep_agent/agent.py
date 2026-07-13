"""Сборка native DeepAgents агента для аналитики данных и работы с кодом.

Главный файл сборки. Точка входа — :func:`build_agent`: она собирает
supervisor по нумерованным шагам (settings -> data tools -> middleware -> backend ->
subagents -> custom tools -> ``create_deep_agent``).

Как редактировать/кастомизировать (подробности — в ``README.md``):
- Данные: передай свои ``data_tools=[...]`` в :func:`build_agent`.
- Внешние инструменты supervisor: передай свои ``supervisor_tools=[...]`` в :func:`build_agent`.
- Конфиг и пороги: Python-defaults в ``agent_settings.py``.
- Поведение supervisor/subagent: правь тематические модули в ``prompts`` без доменной логики.
- Доменные знания: добавляй/редактируй корневые ``skills/<name>/SKILL.md`` — менять код не нужно.
- Новые subagents: добавь конфигурацию в ``subagents.py``.

Служебные функции:
- build_agent: сборка supervisor и subagents.
- _normalize_tools: проверка и нормализация списка инструментов.
- build_shell_workspace_backend: сборка shell-capable workspace backend для supervisor и coding-agent.
- build_filesystem_workspace_backend: сборка filesystem-only backend для data-agent.
- _normalize_virtual_directory: нормализация state-маршрута текстовых артефактов.
- _build_state_artifact_routes: сборка безопасных route-ов для state-артефактов.
- _is_reserved_workspace_artifact_route: проверка конфликта route-а с реальными artifacts.
- _resolve_workspace_root: проверка рабочей директории.
- _agents_memory_path: workspace-путь ``AGENTS.md``.
- _find_spark_session_factory: поиск SparkSession factory в data-tools.
- _register_deepagents_profile: отключение базового prompt и general-purpose subagent DeepAgents.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from deepagents.backends import CompositeBackend, StateBackend
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from deep_agent.execution.filesystem_backend import (
    Utf8FilesystemBackend,
    Utf8LocalShellBackend,
)
from deep_agent.data_processing.load_data_result import wrap_data_tools_with_query_code
from deep_agent.middleware.filesystem_path_middleware import FilesystemPathContractMiddleware
from deep_agent.middleware.gigachat_runtime_middleware import (
    LoopBreakerMiddleware,
    ShellSafetyMiddleware,
)
from deep_agent.middleware.tool_context_middleware import ToolContextNoticeMiddleware
from deep_agent.middleware.tool_description_middleware import (
    DiagnosticLoggingMiddleware,
    PromptToolDescriptionsMiddleware,
    PromptToolFilterMiddleware,
)
from deep_agent.prompts.tool_description_prompt import TOOL_DESCRIPTION_OVERRIDES
from deep_agent.agent_settings import (
    AgentSettings,
    DEFAULT_TOOL_OUTPUTS_RELATIVE_PATH,
    load_agent_settings,
    workspace_tool_path,
)
from deep_agent.middleware.model_error_middleware import (
    format_model_error,
    is_retryable_model_error,
)
from deep_agent.middleware.prompt_logging_middleware import PromptLoggingMiddleware
from deep_agent.memory.user_profile_memory import build_user_profile_memory_reference

_DEFAULT_CHECKPOINTER = object()


def _register_deepagents_profile(model: str | BaseChatModel) -> None:
    """Настраивает служебный профиль DeepAgents для переданной модели.

    Args:
        model: Строковая спецификация модели DeepAgents или экземпляр ``BaseChatModel``.

    Returns:
        ``None``. Функция отключает базовый prompt и автоматический general-purpose
        subagent, оставляя только явно собранные роли проекта.

    Raises:
        ValueError: Если для экземпляра модели нельзя определить provider и identifier.
    """

    if isinstance(model, str):
        profile_key = model
    else:
        from deepagents._models import get_model_identifier, get_model_provider

        identifier = get_model_identifier(model)
        provider = get_model_provider(model)
        if not identifier or not provider:
            raise ValueError(
                "Невозможно определить provider и identifier модели для регистрации HarnessProfile."
            )
        profile_key = identifier if ":" in identifier else f"{provider}:{identifier}"

    register_harness_profile(
        profile_key,
        HarnessProfile(
            base_system_prompt="",
            system_prompt_suffix="",
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def _normalize_tools(
    raw_tools: Any,
    *,
    parameter_name: str,
    allow_none: bool = False,
) -> list[BaseTool]:
    """Приводит переданные инструменты к списку ``BaseTool`` с проверкой типов.

    Args:
        raw_tools: Один ``BaseTool``, список/кортеж tools или ``None``.
        parameter_name: Имя параметра для понятного текста ошибки.
        allow_none: Разрешено ли значение ``None``.

    Returns:
        Список валидированных data-tools.
    """

    if raw_tools is None and allow_none:
        return []
    if isinstance(raw_tools, BaseTool):
        return [raw_tools]
    if not isinstance(raw_tools, (list, tuple)):
        none_suffix = " или None" if allow_none else ""
        raise TypeError(
            f"{parameter_name} должен быть BaseTool, списком BaseTool{none_suffix}."
        )

    tools: list[BaseTool] = []
    for item in raw_tools:
        if not isinstance(item, BaseTool):
            raise TypeError(
                f"{parameter_name} содержит объект не BaseTool: {type(item).__name__}"
            )
        tools.append(item)
    return tools


def build_agent(
    *,
    model: Any,
    settings: AgentSettings | None = None,
    data_tools: list[BaseTool] | BaseTool,
    supervisor_tools: list[BaseTool] | BaseTool | None = None,
    workspace_root: str | Path | None = None,
    checkpointer: Any = _DEFAULT_CHECKPOINTER,
    state_artifacts_virtual_dir: str | None = None,
    system_prompt_suffix: str | None = None,
    request_logger: Any | None = None,
) -> Any:
    """Собирает гибридный аналитический и coding DeepAgent.

    Это главная точка сборки агента. Сборка нативная для DeepAgents: supervisor получает
    встроенные tools (`write_todos`, `task`, filesystem, `execute`), custom tools
    `python`, явно переданные supervisor-tools, project memory из ``AGENTS.md`` и два
    специализированных subagents.

    Шаги инициализации (см. нумерацию в теле функции) и точки кастомизации:

    1. Settings — все пороги и пути из ``agent_settings.py`` или готового ``settings``.
    2. Data tools — явно переданные инструменты чтения данных (`load_data`).
    3. Middleware — project-specific skills, paths и diagnostics плюс встроенные
       middleware LangChain/Deep Agents:
       ContextEditingMiddleware (очистка старых tool-результатов при лимите токенов),
       ToolCallLimitMiddleware (общий бюджет вызовов tools),
       ModelRetryMiddleware (повторы ошибок модели),
       нативный ModelCallLimitMiddleware (бюджет ходов одного запуска субагента).
       Кастомизация: пороги в settings; модель выбора skills.
    4. Backend — workspace с terminal, skills и артефактами.
    5. Subagents — отдельный `coding-agent` для кода и `data-retrieval-agent` для таблиц.
    6. Custom tools supervisor — `python` и явно переданные внешние tools.
    7. Сборка `create_deep_agent(...)` со всеми частями.

    Args:
        model: Явно переданная Chat-модель LangChain для supervisor и subagent.
        settings: Готовые настройки; если ``None`` — используются Python-defaults.
        data_tools: Готовые tools чтения данных.
        supervisor_tools: Готовые внешние tools, доступные только supervisor.
        workspace_root: Рабочая директория coding-agent. Имеет приоритет над settings.
        checkpointer: Checkpointer LangGraph для истории диалога. Если аргумент не передан,
            создаётся штатный ``InMemorySaver``. Явный ``None`` передаёт управление
            persistence внешнему Agent Server.
        state_artifacts_virtual_dir: Виртуальная директория для текстовых артефактов,
            сохраняемых в state LangGraph и доступных UI. Если ``None``, state-маршрут
            не создаётся.
        system_prompt_suffix: Дополнительные инструкции, добавляемые к системному prompt.
        request_logger: Логгер пользовательских запросов или ``None``, если запись в БД
            не нужна.
    Returns:
        Скомпилированный DeepAgents граф (supervisor), готовый к ``invoke``/``stream``.
    """

    from deep_agent.agent_graph_builder import (
        _build_agent_backends,
        _build_agent_context,
        _build_agent_tools,
        _build_skills_middleware,
        _build_subagent_graphs,
        _build_supervisor_graph,
    )

    base_data_tools = _normalize_tools(data_tools, parameter_name="data_tools")
    _register_deepagents_profile(model)
    spark_session_factory = _find_spark_session_factory(base_data_tools)
    resolved_settings = settings or load_agent_settings(workspace_root)
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or resolved_settings.workspace_root
    )
    user_profile_memory = (
        build_user_profile_memory_reference(
            workspace_root=resolved_workspace_root,
        )
        if spark_session_factory is not None
        else None
    )

    context = _build_agent_context(
        model=model,
        settings=resolved_settings,
        workspace_root=resolved_workspace_root,
        checkpointer=checkpointer,
        state_artifacts_virtual_dir=state_artifacts_virtual_dir,
        system_prompt_suffix=system_prompt_suffix,
        request_logger=request_logger,
        user_profile_memory=user_profile_memory,
        user_profile_spark_session_factory=spark_session_factory,
        user_memory_paths=(
            [user_profile_memory.memory_path]
            if user_profile_memory is not None
            else []
        ),
    )
    normalized_data_tools = wrap_data_tools_with_query_code(base_data_tools)
    normalized_supervisor_tools = _normalize_tools(
        supervisor_tools,
        parameter_name="supervisor_tools",
        allow_none=True,
    )
    backends = _build_agent_backends(context)
    tools = _build_agent_tools(
        context,
        data_tools=normalized_data_tools,
        supervisor_tools=normalized_supervisor_tools,
    )
    skills_middleware = _build_skills_middleware(context)
    subagents = _build_subagent_graphs(
        context=context,
        backends=backends,
        tools=tools,
        skills_middleware=skills_middleware,
    )
    return _build_supervisor_graph(
        context=context,
        backends=backends,
        tools=tools,
        subagents=subagents,
        skills_middleware=skills_middleware,
    )


def _build_native_runtime_middleware(
    settings: AgentSettings,
    *,
    workspace_root: Path | None = None,
    agent_name: str = "supervisor",
    limit_model_calls: bool,
    hidden_tool_names: tuple[str, ...] = (),
) -> list[Any]:
    """Собирает runtime middleware из публичных реализаций LangChain.

    Args:
        settings: Настройки лимитов и управления контекстом.
        workspace_root: Корень workspace для canonical POSIX-путей filesystem tools.
        agent_name: Имя агента для служебного логирования.
        limit_model_calls: Нужно ли ограничивать число model calls для subagent.
        hidden_tool_names: Имена tools, которые нужно скрыть от модели для этого агента.

    Returns:
        Список middleware для передачи в ``create_deep_agent``.
    """

    middleware: list[Any] = [
        DiagnosticLoggingMiddleware(agent_name),
        PromptToolDescriptionsMiddleware(TOOL_DESCRIPTION_OVERRIDES),
        ShellSafetyMiddleware(),
        LoopBreakerMiddleware(),
        ModelRetryMiddleware(
            max_retries=settings.max_model_retries,
            retry_on=is_retryable_model_error,
            on_failure=format_model_error,
        ),
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
    if workspace_root is not None:
        middleware.insert(
            3,
            FilesystemPathContractMiddleware(
                workspace_root=workspace_root.resolve(),
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
    middleware.append(
        PromptLoggingMiddleware(
            log_dir=Path("debug_prompts"),
            agent_name=agent_name,
        )
    )
    return middleware


def build_shell_workspace_backend(
    settings: AgentSettings | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает backend coding-agent с единым файловым корнем workspace.

    Args:
        settings: Настройки агента; если ``None`` — используются Python-defaults.
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
    routes, artifacts_root = _build_state_artifact_routes(state_artifacts_virtual_dir)

    return CompositeBackend(
        default=Utf8LocalShellBackend(
            root_dir=resolved_workspace_root,
            virtual_mode=True,
            timeout=settings.terminal_timeout,
            max_output_bytes=settings.terminal_max_output_bytes,
            env={},
            inherit_env=False,
        ),
        routes=routes,
        artifacts_root=artifacts_root,
    )


def build_filesystem_workspace_backend(
    settings: AgentSettings | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает filesystem-only backend для data-agent с полным доступом к workspace.

    Args:
        settings: Настройки агента; если ``None``, загружаются defaults.
        workspace_root: Единый корень доступного файлового пространства.
        state_artifacts_virtual_dir: Виртуальная директория UI-артефактов.

    Returns:
        ``CompositeBackend`` без shell, но с чтением и записью всех папок workspace.
    """

    settings = settings or load_agent_settings(workspace_root)
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    routes, artifacts_root = _build_state_artifact_routes(state_artifacts_virtual_dir)

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


def _build_state_artifact_routes(
    state_artifacts_virtual_dir: str | None,
) -> tuple[dict[str, Any], str]:
    """Собирает route-ы state-артефактов без перехвата реальных файлов workspace.

    Args:
        state_artifacts_virtual_dir: Виртуальная директория для state-файлов UI.

    Returns:
        Кортеж из словаря route-ов ``CompositeBackend`` и корня артефактов.
        Если путь совпадает с рабочей директорией artifacts, route не создаётся,
        чтобы supervisor и subagents читали одни и те же файлы с диска.
    """

    if not state_artifacts_virtual_dir:
        return {}, "/"

    artifacts_root = _normalize_virtual_directory(state_artifacts_virtual_dir)
    if _is_reserved_workspace_artifact_route(artifacts_root):
        return {}, artifacts_root
    return {artifacts_root: StateBackend()}, artifacts_root


def _is_reserved_workspace_artifact_route(virtual_dir: str) -> bool:
    """Проверяет, конфликтует ли state route с реальной папкой artifacts.

    Args:
        virtual_dir: Нормализованный виртуальный путь вида ``/name/``.

    Returns:
        ``True``, если route занимает стандартную директорию файловых артефактов
        workspace и не должен направляться в ``StateBackend``.
    """

    first_part = virtual_dir.strip("/").split("/", 1)[0]
    return first_part == DEFAULT_TOOL_OUTPUTS_RELATIVE_PATH


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


def _find_spark_session_factory(data_tools: list[BaseTool]) -> Any | None:
    """Находит фабрику SparkSession в metadata инструмента ``load_data``.

    Args:
        data_tools: Список исходных data-tools до обертки прозрачности.

    Returns:
        Фабрика SparkSession или ``None``.
    """

    for tool in data_tools:
        metadata = getattr(tool, "metadata", None) or {}
        factory = metadata.get("spark_session_factory")
        if callable(factory):
            return factory
    return None


__all__ = [
    "build_agent",
    "build_filesystem_workspace_backend",
    "build_shell_workspace_backend",
]


