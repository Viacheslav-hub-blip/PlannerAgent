"""Сборка native DeepAgents агента для аналитики данных и работы с кодом.

Главный файл сборки. Точка входа — :func:`build_analytics_deep_agent`: она собирает
supervisor по нумерованным шагам (settings -> data tools -> middleware -> backend ->
subagents -> custom tools -> ``create_deep_agent``).

Как редактировать/кастомизировать (подробности — в ``README.md``):
- Данные: передай свои ``data_tools=[...]`` в :func:`build_analytics_deep_agent` или укажи
  ``data_tools_factory`` в конфиге (``resources/config/defaults.json`` / override через
  ``DEEP_AGENT_CONFIG_PATH``).
- Конфиг и пороги: ключи в ``resources/config/defaults.json`` (offload, skills, лимиты).
- Поведение supervisor/subagent: правь тематические модули в ``prompts`` без доменной логики.
- Доменные знания: добавляй/редактируй ``resources/skills/<name>/SKILL.md`` — менять код не нужно.
- Новые subagents: добавь отдельный модуль в ``subagents`` и зарегистрируй его в ``registry.py``.

Служебные функции:
- build_data_tools: сборка инструментов чтения данных через фабрику из настроек.
- _load_callable_from_path: импорт callable по строковому пути.
- _normalize_data_tools: проверка и нормализация списка инструментов.
- build_analytics_deep_agent: сборка supervisor и subagents.
- build_skills_backend: сборка workspace backend для файлов, terminal, skills и tool outputs.
- build_conversation_checkpointer: создание памяти текущего диалога LangGraph.
- _normalize_virtual_directory: нормализация state-маршрута текстовых артефактов.
- _resolve_workspace_root: проверка рабочей директории.
- _build_terminal_environment: безопасный набор переменных окружения terminal.
- _build_file_edit_interrupts: конфигурация approval для изменения файлов.
- _agents_memory_path: виртуальный путь ``AGENTS.md``.
- create_session_tool_outputs_dir: создание папки tool outputs для одного запуска.
- register_session_tool_outputs_cleanup: регистрация удаления tool outputs при закрытии агента.
- cleanup_session_tool_outputs_dir: удаление папки tool outputs одного запуска.
"""

from __future__ import annotations

import atexit
import importlib
import os
import shutil
import uuid
import weakref
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from deepagents import SubAgentMiddleware, create_deep_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

from deep_agent.capabilities import (
    BASE_SUPERVISOR_TOOL_NAMES,
    CODE_WORKSPACE_TOOL_NAMES,
    DATA_RETRIEVAL_TOOL_NAMES,
    GENERAL_PURPOSE_BASE_TOOL_NAMES,
    SUPERVISOR_SKILL_TOOL_GRANTS,
)
from deep_agent.runtime.harness import register_analytics_harness_profile
from deep_agent.runtime.python_sandbox import build_python_sandbox
from deep_agent.subagents.registry import build_subagent_specs
from deep_agent.runtime.filesystem import (
    Utf8FilesystemBackend,
    Utf8LocalShellBackend,
)
from deep_agent.tools.data_result_wrapper import wrap_data_tools_with_query_code
from deep_agent.tools.python_execution import build_execute_python_code_tool
from deep_agent.tools.skill_loader import build_load_skills_tool
from deep_agent.prompts.skills import (
    DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
)
from deep_agent.prompts.coding import GENERAL_PURPOSE_CODING_PROMPT
from deep_agent.prompts.supervisor import SYSTEM_PROMPT
from deep_agent.prompts.tool_contracts import (
    TOOL_DESCRIPTION_OVERRIDES,
)
from deep_agent.settings import DeepAgentSettings, load_deep_agent_settings
from deep_agent.middleware.skills_context import PreloadedSkillsContextMiddleware
from deep_agent.middleware.tool_loop_guard import ToolLoopGuardMiddleware
from deep_agent.middleware.tool_output_file import ToolOutputFileMiddleware
from deep_agent.middleware.tool_descriptions import PromptToolDescriptionsMiddleware
from deep_agent.middleware.tool_visibility import ToolVisibilityMiddleware

_DEFAULT_CHECKPOINTER = object()


def build_data_tools(settings: DeepAgentSettings | None = None) -> list[BaseTool]:
    """Собирает инструменты чтения данных через фабрику из JSON-конфига."""

    settings = settings or load_deep_agent_settings()
    if not settings.data_tools_factory:
        raise ValueError(
            "Не настроена фабрика tools чтения данных. "
            "Передайте data_tools в build_analytics_deep_agent или укажите "
            "data_tools_factory в deep_agent/resources/config/defaults.json или override-конфиге."
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


def build_analytics_deep_agent(
    model: Any,
    settings: DeepAgentSettings | None = None,
    data_tools: list[BaseTool] | None = None,
    workspace_root: str | Path | None = None,
    checkpointer: Any = _DEFAULT_CHECKPOINTER,
    state_artifacts_virtual_dir: str | None = None,
    system_prompt_suffix: str | None = None,
) -> Any:
    """Собирает гибридный аналитический и coding DeepAgent.

    Это главная точка сборки агента. Сборка нативная для DeepAgents: supervisor получает
    встроенные tools (`write_todos`, `task`, filesystem, `execute`), custom tools
    `execute_python_code` и `load_skills`, project memory из ``AGENTS.md`` и два
    специализированных subagents.

    Шаги инициализации (см. нумерацию в теле функции) и точки кастомизации:

    1. Settings — все пороги и пути. Кастомизация: `resources/config/defaults.json`, override-файл
       через env `DEEP_AGENT_CONFIG_PATH`, либо готовый ``settings`` в аргументе.
    2. Data tools — инструменты чтения данных (`load_data`). Кастомизация: передай свои
       ``BaseTool`` в ``data_tools`` или укажи фабрику в ``data_tools_factory`` конфига.
    3. Middleware — два custom-механизма (принудительная загрузка skills, offload больших
       tool outputs в pickle) плюс нативные/кастомные middleware:
       ContextEditingMiddleware (очистка старых tool-результатов при лимите токенов),
       ToolLoopGuardMiddleware (защита от зацикливания на повторных вызовах tool),
       нативный ModelCallLimitMiddleware (бюджет ходов одного запуска субагента).
       Кастомизация: пороги в settings; модель выбора skills.
    4. Backend — workspace с terminal, skills и spill-файлами.
    5. Subagents — `general-purpose` для coding и `data-retrieval-agent` для таблиц.
    6. Custom tools supervisor — `execute_python_code` (расчёты, чтение `.pkl`) и `load_skills` (пакетная загрузка skills).
    7. Сборка `create_deep_agent(...)` со всеми частями.

    Args:
        model: Chat model LangChain для supervisor и subagent.
        settings: Готовые настройки; если ``None`` — загружаются из JSON-конфига.
        data_tools: Готовые tools чтения данных; если ``None`` — берутся из фабрики конфига.
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
    register_analytics_harness_profile(settings.harness_profile_key)
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    session_tool_outputs_dir = create_session_tool_outputs_dir(settings.tool_outputs_dir)

    # Шаг 2. Инструменты чтения данных. Аргумент имеет приоритет над фабрикой из конфига.
    # Оборачиваем их в слой прозрачности: агент получает сгенерированный код запроса и
    # счётчики строк, а большие таблицы корректно уходят в offload (artifact с rows).
    if data_tools is None:
        data_tools = build_data_tools(settings)
    data_tools = wrap_data_tools_with_query_code(data_tools)

    # Шаг 3. Два custom middleware.
    # 3a. Принудительная загрузка skills. Supervisor через LLM выбирает релевантные skills
    #     по запросу и кладёт их контент в system prompt до первого хода модели, кэшируя
    #     выбор в общий словарь. Субагенты переиспользуют этот же выбор (тот же набор
    #     skills, без повторного LLM-вызова и дублей в контексте).
    shared_skills_selection: dict[str, Any] = {}
    supervisor_skills_middleware = PreloadedSkillsContextMiddleware(
        skills_root=settings.skills_root,
        skills_virtual_dir=settings.skills_virtual_dir,
        max_chars_per_file=settings.max_chars_per_skill,
        model=model,
        select_skills=True,
        shared_selection=shared_skills_selection,
        prompt_template=SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    )
    subagent_skills_middleware = PreloadedSkillsContextMiddleware(
        skills_root=settings.skills_root,
        skills_virtual_dir=settings.skills_virtual_dir,
        max_chars_per_file=settings.max_chars_per_skill,
        model=model,
        select_skills=False,
        shared_selection=shared_skills_selection,
        prompt_template=DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    )
    general_purpose_skills_middleware = PreloadedSkillsContextMiddleware(
        skills_root=settings.skills_root,
        skills_virtual_dir=settings.skills_virtual_dir,
        max_chars_per_file=settings.max_chars_per_skill,
        model=model,
        select_skills=False,
        shared_selection=shared_skills_selection,
        prompt_template=SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE,
    )
    # 3b. Offload больших табличных tool outputs в pickle, чтобы не раздувать контекст.
    tool_output_file_middleware = ToolOutputFileMiddleware(
        output_dir=session_tool_outputs_dir,
        min_rows_to_save=settings.tool_output_min_rows_to_save,
        min_content_chars_to_save=settings.tool_output_min_content_chars_to_save,
        preview_rows=settings.tool_output_preview_rows,
        inline_original_content_chars=settings.tool_output_inline_original_chars,
    )
    # 3c. Context editing: очищает старые tool-результаты при достижении лимита токенов,
    #     оставляя последние N (дополняет offload, держит контекст компактным).
    context_editing_middleware = ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=settings.context_edit_trigger_tokens,
                keep=settings.context_edit_keep_tool_results,
            )
        ]
    )
    # 3d. Loop guard: блокирует серию подряд идущих вызовов одного tool после N повторов
    #     и просит модель сменить подход или завершить шаг (защита от зацикливания).
    tool_loop_guard_middleware = ToolLoopGuardMiddleware(
        max_consecutive_tool_calls=settings.max_consecutive_tool_calls,
    )
    # 3e. Prompt-only переопределение descriptions встроенных tools.
    supervisor_tool_descriptions_middleware = PromptToolDescriptionsMiddleware(
        tool_descriptions=TOOL_DESCRIPTION_OVERRIDES,
    )
    subagent_tool_descriptions_middleware = PromptToolDescriptionsMiddleware(
        tool_descriptions=TOOL_DESCRIPTION_OVERRIDES,
    )
    general_purpose_tool_descriptions_middleware = PromptToolDescriptionsMiddleware(
        tool_descriptions={
            name: description
            for name, description in TOOL_DESCRIPTION_OVERRIDES.items()
            if name != "task"
        },
    )
    # 3f. Бюджет шагов субагента: нативный ModelCallLimitMiddleware ограничивает число
    #     ходов модели внутри одного запуска data-retrieval-agent. По исчерпании лимита
    #     (exit_behavior="end") субагент мягко завершается и возвращает supervisor-у то,
    #     что уже собрал, вместо упора в recursion limit графа.
    subagent_step_limit_middleware = ModelCallLimitMiddleware(
        run_limit=settings.max_subagent_model_calls,
        exit_behavior="end",
    )
    # Общие runtime middleware без agent-specific prompt scope.
    base_middleware = [
        tool_output_file_middleware,
        context_editing_middleware,
        tool_loop_guard_middleware,
    ]
    # Supervisor выбирает skills; data-retrieval-agent переиспользует тот же выбор и ограничен
    # бюджетом шагов на запуск.
    supervisor_base_tools = BASE_SUPERVISOR_TOOL_NAMES
    if settings.coding_tools_enabled_by_default:
        supervisor_base_tools = supervisor_base_tools | CODE_WORKSPACE_TOOL_NAMES

    supervisor_middleware = [
        supervisor_skills_middleware,
        ToolVisibilityMiddleware(
            allowed_tools=supervisor_base_tools,
            skill_tool_grants=SUPERVISOR_SKILL_TOOL_GRANTS,
        ),
        *base_middleware,
        supervisor_tool_descriptions_middleware,
    ]
    subagent_middleware = [
        subagent_skills_middleware,
        ToolVisibilityMiddleware(allowed_tools=DATA_RETRIEVAL_TOOL_NAMES),
        *base_middleware,
        subagent_tool_descriptions_middleware,
        subagent_step_limit_middleware,
    ]
    # Workspace backend и дополнительные tools нужны для сборки вложенного general-purpose worker.
    backend = build_skills_backend(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
        state_artifacts_virtual_dir=state_artifacts_virtual_dir,
    )
    python_sandbox = build_python_sandbox(
        settings,
        tool_outputs_dir=session_tool_outputs_dir,
        workspace_root=resolved_workspace_root,
    )
    python_tool = build_execute_python_code_tool(python_sandbox)
    load_skills_tool = build_load_skills_tool(settings)
    file_edit_interrupts = _build_file_edit_interrupts(settings)

    general_purpose_worker_middleware = [
        general_purpose_skills_middleware,
        ToolVisibilityMiddleware(
            allowed_tools=GENERAL_PURPOSE_BASE_TOOL_NAMES - {"task"},
        ),
        *base_middleware,
        general_purpose_tool_descriptions_middleware,
        subagent_step_limit_middleware,
    ]
    general_purpose_worker = create_deep_agent(
        model=model,
        tools=[python_tool, load_skills_tool],
        system_prompt=GENERAL_PURPOSE_CODING_PROMPT,
        backend=backend,
        middleware=general_purpose_worker_middleware,
        memory=[_agents_memory_path(settings.agents_file_name)],
        interrupt_on=file_edit_interrupts,
        name="general-purpose-worker",
    )
    general_purpose_task_middleware = SubAgentMiddleware(
        backend=backend,
        subagents=[
            {
                "name": "general-purpose-worker",
                "description": (
                    "Выполняет независимую задачу по поиску, чтению, изменению файлов "
                    "или запуску локальных проверок без доступа к load_data."
                ),
                "runnable": general_purpose_worker,
            }
        ],
    )
    general_purpose_middleware = [
        general_purpose_skills_middleware,
        general_purpose_task_middleware,
        ToolVisibilityMiddleware(allowed_tools=GENERAL_PURPOSE_BASE_TOOL_NAMES),
        *base_middleware,
        general_purpose_tool_descriptions_middleware,
        subagent_step_limit_middleware,
    ]

    # Шаг 4. Сборка subagents.
    subagents = build_subagent_specs(
        data_tools=[*data_tools, python_tool, load_skills_tool],
        general_purpose_tools=[python_tool, load_skills_tool],
        data_retrieval_middleware=subagent_middleware,
        coding_middleware=general_purpose_middleware,
        model=model,
    )

    # Шаг 6. Финальная сборка DeepAgents supervisor.
    system_prompt = SYSTEM_PROMPT
    if system_prompt_suffix:
        system_prompt = f"{system_prompt}\n\n{system_prompt_suffix.strip()}"

    agent = create_deep_agent(
        model=model,
        tools=[python_tool, load_skills_tool],
        system_prompt=system_prompt,
        subagents=subagents,
        backend=backend,
        middleware=supervisor_middleware,
        memory=[_agents_memory_path(settings.agents_file_name)],
        interrupt_on=file_edit_interrupts,
        checkpointer=(
            build_conversation_checkpointer()
            if checkpointer is _DEFAULT_CHECKPOINTER
            else checkpointer
        ),
    )
    register_session_tool_outputs_cleanup(agent, session_tool_outputs_dir)
    return agent


def build_skills_backend(
    settings: DeepAgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: str | Path | None = None,
    state_artifacts_virtual_dir: str | None = None,
) -> Any:
    """Собирает CompositeBackend с workspace shell, skills и tool outputs.

    Args:
        settings: Настройки агента; если ``None`` — загружаются из JSON-конфига.
        tool_outputs_dir: Папка tool outputs текущего запуска. Если ``None``, используется
            базовая папка из настроек.
        workspace_root: Корень доступного агенту workspace.
        state_artifacts_virtual_dir: Виртуальная директория, направляемая в ``StateBackend``
            для отображения текстовых артефактов в LangGraph UI.

    Returns:
        ``CompositeBackend`` с terminal в workspace и маршрутами skills/tool outputs/artifacts.
    """

    from deepagents.backends import CompositeBackend, StateBackend

    settings = settings or load_deep_agent_settings()
    resolved_workspace_root = _resolve_workspace_root(
        workspace_root or settings.workspace_root
    )
    resolved_tool_outputs_dir = tool_outputs_dir or settings.tool_outputs_dir
    tool_outputs_virtual = "/tool_outputs/"
    routes = {
        settings.skills_virtual_dir: Utf8FilesystemBackend(
            root_dir=settings.skills_root,
            virtual_mode=True,
        ),
        tool_outputs_virtual: Utf8FilesystemBackend(
            root_dir=resolved_tool_outputs_dir,
            virtual_mode=True,
        ),
    }
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


def _build_file_edit_interrupts(
    settings: DeepAgentSettings,
) -> dict[str, Any] | None:
    """Создаёт approval policy только для файловых изменений.

    Args:
        settings: Настройки с флагом включения approval.

    Returns:
        Конфигурация HITL для ``write_file`` и ``edit_file`` либо ``None``.
    """

    if not settings.enable_interrupts:
        return None
    config = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "Изменение файла в рабочем workspace требует подтверждения.",
    }
    return {
        "write_file": dict(config),
        "edit_file": dict(config),
    }


def _agents_memory_path(file_name: str) -> str:
    """Преобразует имя project memory в абсолютный виртуальный путь.

    Args:
        file_name: Имя или относительный путь ``AGENTS.md`` в workspace.

    Returns:
        POSIX-путь, подходящий для ``create_deep_agent(memory=...)``.

    Raises:
        ValueError: Путь пытается выйти за пределы workspace.
    """

    normalized = str(file_name or "AGENTS.md").strip().replace("\\", "/").lstrip("/")
    normalized = normalized or "AGENTS.md"
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError("Путь AGENTS.md не должен выходить за пределы workspace.")
    return f"/{normalized}"


def create_session_tool_outputs_dir(base_dir: Path) -> Path:
    """Создаёт отдельную папку tool outputs для одного запуска агента.

    Args:
        base_dir: Базовая директория, внутри которой создаётся session-подкаталог.

    Returns:
        Абсолютный путь к созданной папке текущего запуска.
    """

    base_dir.mkdir(parents=True, exist_ok=True)
    session_dir = base_dir / f"session_{uuid.uuid4().hex}"
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir.resolve()


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
    """Удаляет папку tool outputs одного запуска.

    Args:
        session_dir: Папка текущего запуска, имя которой должно начинаться с ``session_``.

    Returns:
        ``None``. Если путь не похож на session-папку, функция ничего не удаляет.
    """

    resolved = session_dir.resolve()
    if not resolved.name.startswith("session_"):
        return
    shutil.rmtree(resolved, ignore_errors=True)


__all__ = [
    "build_analytics_deep_agent",
    "build_conversation_checkpointer",
    "build_data_tools",
    "build_skills_backend",
    "cleanup_session_tool_outputs_dir",
    "create_session_tool_outputs_dir",
    "register_session_tool_outputs_cleanup",
]
