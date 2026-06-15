"""Конфигурация аналитического DeepAgent.

Содержит:
- DeepAgentSettings: типизированные настройки сборки агента.
- DeepAgentSettings.from_mapping: сборка настроек из словаря.
- load_deep_agent_settings: загрузка defaults-конфига и override-конфига.
- _load_config_payload: чтение и объединение JSON-конфигов.
- _read_json_file: чтение JSON-файла.
- _validate_required_config_keys: проверка обязательных ключей.
- _resolve_project_path: приведение пути к абсолютному.
- _resolve_workspace_path: разрешение и проверка пути внутри workspace.
- workspace_tool_path: преобразование реального пути в путь filesystem tools.
- _int_from_config: чтение целого числа из конфига.
- _bool_from_config: чтение boolean из конфига.
- _dict_from_config: чтение словаря из конфига.
- _optional_str_from_config: чтение опциональной строки из конфига.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "defaults.json"
CONFIG_ENV_VAR = "DEEP_AGENT_CONFIG_PATH"
REQUIRED_CONFIG_KEYS = (
    "harness_profile_key",
    "thread_id",
    "workspace_root",
    "agents_file_name",
    "enable_interrupts",
    "terminal_timeout",
    "terminal_max_output_bytes",
    "skills_root",
    "data_tools_factory",
    "data_tools_factory_kwargs",
    "tool_outputs_dir",
    "tool_output_min_rows_to_save",
    "tool_output_min_content_chars_to_save",
    "tool_output_preview_rows",
    "tool_output_inline_original_chars",
    "context_edit_trigger_tokens",
    "context_edit_keep_tool_results",
    "read_file_default_limit",
    "max_model_retries",
    "max_tool_calls_per_run",
    "max_subagent_model_calls",
    "graph_recursion_limit",
    "trace_log_dir",
)


@dataclass(frozen=True)
class DeepAgentSettings:
    """Настройки сборки и запуска аналитического DeepAgent."""

    harness_profile_key: str
    thread_id: str
    workspace_root: Path
    agents_file_name: str
    enable_interrupts: bool
    terminal_timeout: int
    terminal_max_output_bytes: int
    skills_root: Path
    data_tools_factory: str | None
    data_tools_factory_kwargs: dict[str, Any]
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

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], project_root: Path = PROJECT_ROOT) -> "DeepAgentSettings":
        """Собирает типизированные настройки из словаря конфигурации.

        Args:
            payload: Сырой словарь из JSON-конфига (defaults + override).
            project_root: Корень проекта для разрешения относительных путей.

        Returns:
            Готовый ``DeepAgentSettings``.

        Raises:
            ValueError: Не хватает обязательного ключа или ключ имеет неверный тип.
        """

        _validate_required_config_keys(payload)
        workspace_root = _resolve_project_path(payload["workspace_root"], project_root)
        return cls(
            harness_profile_key=str(payload["harness_profile_key"]),
            thread_id=str(payload["thread_id"]),
            workspace_root=workspace_root,
            agents_file_name=str(payload["agents_file_name"]).strip() or "AGENTS.md",
            enable_interrupts=_interrupts_enabled_from_config(payload),
            terminal_timeout=_int_from_config(payload, "terminal_timeout"),
            terminal_max_output_bytes=_int_from_config(
                payload,
                "terminal_max_output_bytes",
            ),
            skills_root=_resolve_workspace_path(payload["skills_root"], workspace_root),
            data_tools_factory=_optional_str_from_config(payload, "data_tools_factory"),
            data_tools_factory_kwargs=_dict_from_config(payload, "data_tools_factory_kwargs"),
            tool_outputs_dir=_resolve_workspace_path(
                payload["tool_outputs_dir"],
                workspace_root,
            ),
            tool_output_min_rows_to_save=_int_from_config(payload, "tool_output_min_rows_to_save"),
            tool_output_min_content_chars_to_save=_int_from_config(
                payload,
                "tool_output_min_content_chars_to_save",
            ),
            tool_output_preview_rows=_int_from_config(payload, "tool_output_preview_rows"),
            tool_output_inline_original_chars=_int_from_config(payload, "tool_output_inline_original_chars"),
            context_edit_trigger_tokens=_int_from_config(payload, "context_edit_trigger_tokens"),
            context_edit_keep_tool_results=_int_from_config(payload, "context_edit_keep_tool_results"),
            read_file_default_limit=_int_from_config(payload, "read_file_default_limit"),
            max_model_retries=_int_from_config(payload, "max_model_retries"),
            max_tool_calls_per_run=_int_from_config(payload, "max_tool_calls_per_run"),
            max_subagent_model_calls=_int_from_config(payload, "max_subagent_model_calls"),
            graph_recursion_limit=_int_from_config(payload, "graph_recursion_limit"),
            trace_log_dir=_resolve_workspace_path(payload["trace_log_dir"], workspace_root),
        )


def load_deep_agent_settings(config_path: str | Path | None = None) -> DeepAgentSettings:
    """Загружает настройки агента из JSON-конфига (defaults + опциональный override)."""

    payload = _load_config_payload(config_path)
    return DeepAgentSettings.from_mapping(payload)


def _load_config_payload(config_path: str | Path | None = None) -> dict[str, Any]:
    """Читает defaults-конфиг и мёржит поверх него override (аргумент или env)."""

    default_payload = _read_json_file(DEFAULT_CONFIG_PATH)
    raw_path = config_path or os.environ.get(CONFIG_ENV_VAR)
    if raw_path is None:
        return default_payload

    custom_path = Path(raw_path)
    if custom_path.resolve() == DEFAULT_CONFIG_PATH.resolve():
        return default_payload

    custom_payload = _read_json_file(custom_path)
    return {**default_payload, **custom_payload}


def _read_json_file(path: Path) -> dict[str, Any]:
    """Читает JSON-файл и проверяет, что он содержит объект (dict)."""

    resolved_path = path.resolve()
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config file must contain JSON object: {resolved_path}")
    return payload


def _validate_required_config_keys(payload: dict[str, Any]) -> None:
    """Проверяет наличие всех обязательных ключей конфига, иначе бросает ValueError."""

    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in payload]
    if missing_keys:
        raise ValueError(f"DeepAgent config missing required keys: {', '.join(missing_keys)}")


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
        Путь вида ``/deep_agent/skills/``, однозначно соответствующий
        ``workspace_root/deep_agent/skills``.

    Raises:
        ValueError: Путь находится вне workspace.
    """

    resolved_root = workspace_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"Path must be inside workspace_root: {resolved_path}") from None

    result = f"/{relative_path.as_posix()}" if relative_path.parts else "/"
    if directory and not result.endswith("/"):
        result += "/"
    return result


def _int_from_config(payload: dict[str, Any], key: str) -> int:
    """Читает int-ключ конфига, иначе бросает ValueError с именем ключа."""

    try:
        return int(payload[key])
    except (TypeError, ValueError):
        raise ValueError(f"Config key '{key}' must be an integer.") from None


def _interrupts_enabled_from_config(payload: dict[str, Any]) -> bool:
    """Читает флаг HITL: ``enable_interrupts`` или устаревший ``enable_file_edit_approval``."""

    if "enable_interrupts" in payload:
        return _bool_from_config(payload, "enable_interrupts")
    if "enable_file_edit_approval" in payload:
        return _bool_from_config(payload, "enable_file_edit_approval")
    raise ValueError(
        "DeepAgent config must define 'enable_interrupts' "
        "(or legacy 'enable_file_edit_approval')."
    )


def _bool_from_config(payload: dict[str, Any], key: str) -> bool:
    """Читает boolean-ключ конфига, иначе бросает ValueError.

    Args:
        payload: Словарь конфигурации.
        key: Имя обязательного ключа.

    Returns:
        Значение ``bool`` из конфигурации.

    Raises:
        ValueError: Значение ключа не является ``bool``.
    """

    value = payload[key]
    if isinstance(value, bool):
        return value
    raise ValueError(f"Config key '{key}' must be a boolean.")


def _dict_from_config(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """Читает dict-ключ конфига, иначе бросает ValueError с именем ключа."""

    value = payload[key]
    if isinstance(value, dict):
        return dict(value)
    raise ValueError(f"Config key '{key}' must be an object.")


def _optional_str_from_config(payload: dict[str, Any], key: str) -> str | None:
    """Читает строковый ключ конфига, допускающий ``null`` (возвращает ``None``)."""

    value = payload[key]
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError(f"Config key '{key}' must be a string or null.")


__all__ = [
    "CONFIG_ENV_VAR",
    "DEFAULT_CONFIG_PATH",
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "REQUIRED_CONFIG_KEYS",
    "DeepAgentSettings",
    "load_deep_agent_settings",
    "workspace_tool_path",
]
