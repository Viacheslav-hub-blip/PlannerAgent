"""Python-настройки аналитического DeepAgent.

Содержит:
- AgentSettings: типизированные настройки сборки агента.
- load_agent_settings: сборка настроек из Python-defaults.
- _resolve_project_path: приведение пути к абсолютному.
- _resolve_workspace_path: разрешение и проверка пути внутри workspace.
- workspace_tool_root: виртуальный корень filesystem tools.
- workspace_tool_path: преобразование реального пути в путь filesystem tools.
- workspace_tool_root_aliases: список абсолютных ОС-префиксов, эквивалентных виртуальному корню tools.
- strip_workspace_tool_prefix: преобразование tool-пути или ОС-пути workspace в путь относительно workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_AGENTS_FILE_NAME = "AGENTS.md"
DEFAULT_SKILLS_RELATIVE_PATH = "skills"
DEFAULT_TOOL_OUTPUTS_RELATIVE_PATH = "artifacts"
DEFAULT_TRACE_LOG_RELATIVE_PATH = "artifacts"
DEFAULT_HARNESS_PROFILE_KEY = "kitai"
DEFAULT_THREAD_ID = "analytics-chat-001"
DEFAULT_TERMINAL_TIMEOUT = 120
DEFAULT_TERMINAL_MAX_OUTPUT_BYTES = 100_000
DEFAULT_TOOL_OUTPUT_MIN_ROWS_TO_SAVE = 30
DEFAULT_TOOL_OUTPUT_MIN_CONTENT_CHARS_TO_SAVE = 60_000
DEFAULT_TOOL_OUTPUT_PREVIEW_ROWS = 30
DEFAULT_TOOL_OUTPUT_INLINE_ORIGINAL_CHARS = 10_000
DEFAULT_CONTEXT_EDIT_TRIGGER_TOKENS = 100_000
DEFAULT_CONTEXT_EDIT_KEEP_TOOL_RESULTS = 3
DEFAULT_READ_FILE_DEFAULT_LIMIT = 500
DEFAULT_MAX_MODEL_RETRIES = 5
DEFAULT_MAX_TOOL_CALLS_PER_RUN = 40
DEFAULT_MAX_SUBAGENT_MODEL_CALLS = 19
DEFAULT_GRAPH_RECURSION_LIMIT = 100


@dataclass(frozen=True)
class AgentSettings:
    """Настройки сборки и запуска аналитического DeepAgent."""

    harness_profile_key: str
    thread_id: str
    workspace_root: Path
    agents_file_name: str
    terminal_timeout: int
    terminal_max_output_bytes: int
    skills_root: Path
    tool_outputs_dir: Path
    tool_output_min_rows_to_save: int
    tool_output_min_content_chars_to_save: int
    tool_output_preview_rows: int
    tool_output_inline_original_chars: int
    context_edit_trigger_tokens: int
    context_edit_keep_tool_results: int
    read_file_default_limit: int
    max_model_retries: int
    max_tool_calls_per_run: int
    max_subagent_model_calls: int
    graph_recursion_limit: int
    trace_log_dir: Path

def load_agent_settings(workspace_root: str | Path | None = None) -> AgentSettings:
    """Собирает настройки агента из Python-defaults.

    Args:
        workspace_root: Корень workspace. Если ``None``, используется корень проекта.

    Returns:
        Готовый ``AgentSettings`` без JSON override-конфига.
    """

    resolved_workspace_root = _resolve_project_path(
        workspace_root or PROJECT_ROOT,
        PROJECT_ROOT,
    )
    return AgentSettings(
        harness_profile_key=DEFAULT_HARNESS_PROFILE_KEY,
        thread_id=DEFAULT_THREAD_ID,
        workspace_root=resolved_workspace_root,
        agents_file_name=DEFAULT_AGENTS_FILE_NAME,
        terminal_timeout=DEFAULT_TERMINAL_TIMEOUT,
        terminal_max_output_bytes=DEFAULT_TERMINAL_MAX_OUTPUT_BYTES,
        skills_root=_resolve_workspace_path(
            DEFAULT_SKILLS_RELATIVE_PATH,
            resolved_workspace_root,
        ),
        tool_outputs_dir=_resolve_workspace_path(
            DEFAULT_TOOL_OUTPUTS_RELATIVE_PATH,
            resolved_workspace_root,
        ),
        tool_output_min_rows_to_save=DEFAULT_TOOL_OUTPUT_MIN_ROWS_TO_SAVE,
        tool_output_min_content_chars_to_save=DEFAULT_TOOL_OUTPUT_MIN_CONTENT_CHARS_TO_SAVE,
        tool_output_preview_rows=DEFAULT_TOOL_OUTPUT_PREVIEW_ROWS,
        tool_output_inline_original_chars=DEFAULT_TOOL_OUTPUT_INLINE_ORIGINAL_CHARS,
        context_edit_trigger_tokens=DEFAULT_CONTEXT_EDIT_TRIGGER_TOKENS,
        context_edit_keep_tool_results=DEFAULT_CONTEXT_EDIT_KEEP_TOOL_RESULTS,
        read_file_default_limit=DEFAULT_READ_FILE_DEFAULT_LIMIT,
        max_model_retries=DEFAULT_MAX_MODEL_RETRIES,
        max_tool_calls_per_run=DEFAULT_MAX_TOOL_CALLS_PER_RUN,
        max_subagent_model_calls=DEFAULT_MAX_SUBAGENT_MODEL_CALLS,
        graph_recursion_limit=DEFAULT_GRAPH_RECURSION_LIMIT,
        trace_log_dir=_resolve_workspace_path(
            DEFAULT_TRACE_LOG_RELATIVE_PATH,
            resolved_workspace_root,
        ),
    )


def _resolve_project_path(value: Any, project_root: Path) -> Path:
    """Приводит значение к абсолютному пути относительно корня проекта."""

    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _resolve_workspace_path(value: Any, workspace_root: Path) -> Path:
    """Разрешает путь относительно workspace и запрещает выход за его пределы.

    Args:
        value: Абсолютный путь или путь относительно ``workspace_root``.
        workspace_root: Настроенный корень файлового пространства агента.

    Returns:
        Абсолютный путь внутри ``workspace_root``.

    Raises:
        ValueError: Разрешённый путь находится вне ``workspace_root``.
    """

    path = Path(str(value))
    resolved = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"Config path must be inside workspace_root: {resolved}"
        ) from None
    return resolved


def workspace_tool_root(workspace_root: Path) -> str:
    """Возвращает виртуальный POSIX-корень workspace для интерфейса tools.

    Args:
        workspace_root: Реальный корень файлового пространства агента.

    Returns:
        Канонический корень ``/``. Реальный ``workspace_root`` не включается в
        ответы tools, чтобы supervisor и subagents видели одинаковые пути.
    """

    return "/"


def workspace_tool_root_aliases(workspace_root: Path) -> tuple[str, ...]:
    """Возвращает ОС-пути workspace, которые считаются алиасами виртуального корня.

    Args:
        workspace_root: Реальный корень файлового пространства агента.

    Returns:
        Кортеж POSIX-префиксов, например ``/home/user_id_omega-sbrf-ru``. На Windows
        дополнительно поддерживается исторический вид ``/C:/Users/...``.
    """

    raw_path = workspace_root.resolve().as_posix().rstrip("/")
    aliases: list[str] = []
    if raw_path and raw_path != "/":
        aliases.append(raw_path)
        if ":" in raw_path and not raw_path.startswith("/"):
            aliases.append(f"/{raw_path}")
    return tuple(dict.fromkeys(aliases))


def strip_workspace_tool_prefix(value: str, workspace_root: Path) -> str | None:
    """Срезает виртуальный или ОС-префикс workspace и возвращает относительный POSIX-путь.

    Args:
        value: Путь из tool-вызова, подсказки или Python-кода агента.
        workspace_root: Реальный корень файлового пространства агента.

    Returns:
        Путь относительно workspace без начального слеша, пустую строку для корня
        workspace или ``None``, если путь не похож на workspace/tool-путь.
    """

    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized:
        return None
    for alias in sorted(
        workspace_tool_root_aliases(workspace_root),
        key=len,
        reverse=True,
    ):
        prefix = alias.rstrip("/")
        if normalized == prefix:
            return ""
        if normalized.startswith(f"{prefix}/"):
            return normalized[len(prefix) :].lstrip("/")
    if normalized == "/":
        return ""
    if normalized.startswith("/") and not _is_windows_drive_path(normalized.lstrip("/")):
        return normalized.lstrip("/")
    return None


def _is_windows_drive_path(value: str) -> bool:
    """Проверяет, начинается ли POSIX-строка с Windows drive-префикса.

    Args:
        value: Нормализованная строка пути без начального виртуального слеша.

    Returns:
        ``True``, если строка начинается с префикса вида ``C:/``.
    """

    return len(value) >= 3 and value[1:3] == ":/" and value[0].isalpha()


def workspace_tool_path(
    path: Path,
    workspace_root: Path,
    *,
    directory: bool = False,
) -> str:
    """Преобразует реальный путь внутри workspace в путь filesystem tools.

    Args:
        path: Реальный абсолютный путь.
        workspace_root: Корень файлового пространства агента.
        directory: Нужно ли добавить завершающий слеш.

    Returns:
        Виртуальный путь вида ``/skills/``, однозначно соответствующий
        ``workspace_root/skills``.

    Raises:
        ValueError: Путь находится вне workspace.
    """

    resolved_root = workspace_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"Path must be inside workspace_root: {resolved_path}") from None

    tool_root = workspace_tool_root(resolved_root)
    if relative_path.parts:
        base = tool_root.rstrip("/")
        relative_posix = relative_path.as_posix()
        result = f"{base}/{relative_posix}" if base else f"/{relative_posix}"
    else:
        result = tool_root
    if directory and not result.endswith("/"):
        result += "/"
    return result


__all__ = [
    "AgentSettings",
    "DEFAULT_AGENTS_FILE_NAME",
    "DEFAULT_CONTEXT_EDIT_KEEP_TOOL_RESULTS",
    "DEFAULT_CONTEXT_EDIT_TRIGGER_TOKENS",
    "DEFAULT_GRAPH_RECURSION_LIMIT",
    "DEFAULT_HARNESS_PROFILE_KEY",
    "DEFAULT_MAX_MODEL_RETRIES",
    "DEFAULT_MAX_SUBAGENT_MODEL_CALLS",
    "DEFAULT_MAX_TOOL_CALLS_PER_RUN",
    "DEFAULT_READ_FILE_DEFAULT_LIMIT",
    "DEFAULT_SKILLS_RELATIVE_PATH",
    "DEFAULT_TERMINAL_MAX_OUTPUT_BYTES",
    "DEFAULT_TERMINAL_TIMEOUT",
    "DEFAULT_THREAD_ID",
    "DEFAULT_TOOL_OUTPUT_INLINE_ORIGINAL_CHARS",
    "DEFAULT_TOOL_OUTPUT_MIN_CONTENT_CHARS_TO_SAVE",
    "DEFAULT_TOOL_OUTPUT_MIN_ROWS_TO_SAVE",
    "DEFAULT_TOOL_OUTPUT_PREVIEW_ROWS",
    "DEFAULT_TOOL_OUTPUTS_RELATIVE_PATH",
    "DEFAULT_TRACE_LOG_RELATIVE_PATH",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "load_agent_settings",
    "strip_workspace_tool_prefix",
    "workspace_tool_root_aliases",
    "workspace_tool_root",
    "workspace_tool_path",
]

