"""Persistent Python runtime для DeepAgent с helpers чтения pickle и файлов.

Содержит:
- DeepAgentPythonSandbox: persistent runtime для выполнения Python-кода.
- build_python_sandbox: фабрика runtime с рабочей директорией workspace.
"""

from __future__ import annotations

import builtins
import os
import pathlib
import pickle
import types
from pathlib import Path
from typing import Any

from deep_agent.agent_settings import (
    AgentSettings,
    strip_workspace_tool_prefix,
    workspace_tool_path,
)

SANDBOX_HELPER_NAMES = frozenset(
    {
        "ARTIFACTS_DIR",
        "PROJECT_ROOT",
        "WORKSPACE_ROOT",
        "read_pickle_file",
        "describe_pickle_file",
        "resolve_workspace_path",
        "rows_to_dataframe",
    }
)


class DeepAgentPythonSandbox:
    """In-memory runtime с общими переменными между вызовами tool ``python``."""

    def __init__(
        self,
        *,
        working_directory: Path,
        readable_roots: tuple[Path, ...],
        tool_outputs_dir: Path,
    ) -> None:
        """Создаёт sandbox с общим словарём ``globals`` и seed-helpers.

        Args:
            working_directory: Рабочая директория для относительных путей в коде.
            readable_roots: Информационные корни workspace и tool outputs для ответа tool.
            tool_outputs_dir: Папка spill-файлов (`.pkl`) после offload middleware.
        """

        self.working_directory = working_directory.resolve()
        self.readable_roots = tuple(path.resolve() for path in readable_roots)
        self.tool_outputs_dir = tool_outputs_dir.resolve()
        self.tool_outputs_dir.mkdir(parents=True, exist_ok=True)
        self.globals: dict[str, Any] = {}
        self.last_dataframe_variable: str | None = None
        self._seed_helpers()

    def _seed_helpers(self) -> None:
        """Заполняет ``globals`` helpers чтения pickle и библиотеками pandas/numpy.

        Добавляет ``PROJECT_ROOT``, ``WORKSPACE_ROOT``, ``ARTIFACTS_DIR``,
        helpers чтения и (если доступны) ``pd``/``np``.
        Полные workspace-пути преобразуются в реальные пути текущего запуска.
        """

        tool_outputs_dir = self.tool_outputs_dir
        project_root = self.working_directory

        def _resolve_workspace_path(path: Path) -> Path:
            """Преобразует путь относительно настроенного workspace в реальный путь.

            Args:
                path: Исходный путь из пользовательского Python-кода.

            Returns:
                Абсолютный путь внутри текущего workspace или исходный абсолютный путь.
            """

            raw_path = str(path)
            if path.is_absolute():
                resolved_path = path.expanduser().resolve()
                for readable_root in self.readable_roots:
                    try:
                        resolved_path.relative_to(readable_root)
                    except ValueError:
                        continue
                    return resolved_path
            relative_path = strip_workspace_tool_prefix(raw_path, project_root)
            if relative_path is not None:
                path = project_root / relative_path if relative_path else project_root
            elif raw_path.startswith(("/", "\\")) and not path.drive:
                relative_path = raw_path.lstrip("/\\")
                path = project_root / relative_path
            elif not path.is_absolute():
                path = project_root / path
            return path.expanduser().resolve()

        def _assert_readable_path(path: Path, source_path: str | os.PathLike[str] | None = None) -> Path:
            """Разрешает путь и проверяет, что файл существует.

            Args:
                path: Путь, который нужно проверить после нормализации.
                source_path: Исходное значение из пользовательского Python-кода.

            Returns:
                Реальный путь к существующему файлу.
            """

            resolved = _resolve_workspace_path(path)
            if not resolved.exists():
                source_text = "" if source_path is None else f" source_path={source_path!s};"
                raise FileNotFoundError(
                    f"Файл не найден:{source_text} resolved_path={resolved}; "
                    f"workspace_root={project_root}"
                )
            return resolved

        def resolve_workspace_path(file_path: str | os.PathLike[str]) -> Path:
            """Преобразует workspace-путь или относительный путь в реальный путь ОС.

            Args:
                file_path: Путь вида ``/artifacts/file.pkl``, относительный путь внутри
                    workspace или абсолютный разрешенный путь ОС.

            Returns:
                Реальный ``Path`` внутри workspace или каталога артефактов.
            """

            return _resolve_workspace_path(Path(file_path))

        def read_pickle_file(file_path: str) -> Any:
            """Читает pickle-файл по абсолютному или относительному пути."""

            path = _assert_readable_path(resolve_workspace_path(file_path), file_path)
            with path.open("rb") as file:
                return pickle.load(file)

        def describe_pickle_file(file_path: str) -> dict[str, Any]:
            """Возвращает компактное описание содержимого pickle без полной загрузки в память агента."""

            data = read_pickle_file(file_path)
            description: dict[str, Any] = {
                "file_path": str(_assert_readable_path(resolve_workspace_path(file_path), file_path)),
                "python_type": type(data).__name__,
            }
            if isinstance(data, list):
                description["rows_count"] = len(data)
                if data and isinstance(data[0], dict):
                    description["columns"] = sorted({key for row in data for key in row})
                    description["preview_rows"] = data[:3]
            elif hasattr(data, "shape"):
                description["shape"] = getattr(data, "shape", None)
                description["columns"] = list(getattr(data, "columns", []))
            return description

        def rows_to_dataframe(rows: Any, *, columns: list[str] | None = None) -> Any:
            """Преобразует list[dict] или совместимую структуру в pandas DataFrame."""

            import pandas as pd

            frame = pd.DataFrame(rows, columns=columns)
            return frame

        default_open = builtins.open

        def sandbox_open(
            file: Any,
            mode: str = "r",
            buffering: int = -1,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
            closefd: bool = True,
            opener: Any | None = None,
        ) -> Any:
            """Открывает файл с преобразованием workspace-путей sandbox.

            Args:
                file: Путь к файлу или файловый дескриптор.
                mode: Режим открытия файла.
                buffering: Настройка буферизации стандартной функции ``open``.
                encoding: Кодировка текстового файла.
                errors: Политика обработки ошибок кодировки.
                newline: Политика обработки переносов строк.
                closefd: Нужно ли закрывать файловый дескриптор при закрытии файла.
                opener: Пользовательский opener для стандартной функции ``open``.

            Returns:
                Файловый объект, открытый стандартной функцией ``open``.
            """

            if isinstance(file, int):
                return default_open(
                    file,
                    mode,
                    buffering,
                    encoding,
                    errors,
                    newline,
                    closefd,
                    opener,
                )

            resolved = _resolve_workspace_path(Path(os.fsdecode(file)))
            return default_open(
                resolved,
                mode,
                buffering,
                encoding,
                errors,
                newline,
                closefd,
                opener,
            )

        self.globals.update(
            {
                "ARTIFACTS_DIR": str(tool_outputs_dir),
                "PROJECT_ROOT": str(project_root),
                "WORKSPACE_ROOT": str(project_root),
                "resolve_workspace_path": resolve_workspace_path,
                "read_pickle_file": read_pickle_file,
                "describe_pickle_file": describe_pickle_file,
                "rows_to_dataframe": rows_to_dataframe,
            }
        )
        helper_module = types.ModuleType("functions")
        for helper_name in SANDBOX_HELPER_NAMES:
            setattr(helper_module, helper_name, self.globals[helper_name])
        pathlib_module = types.ModuleType("pathlib")
        pathlib_module.__dict__.update(vars(pathlib))

        def runtime_path(*args: Any, **kwargs: Any) -> Path:
            """Создаёт ``Path`` с преобразованием workspace tool-путей."""

            if not args:
                return pathlib.Path(**kwargs)
            first, *rest = args
            resolved = _resolve_workspace_path(pathlib.Path(os.fsdecode(first)))
            return resolved.joinpath(*rest)

        pathlib_module.Path = runtime_path

        default_import = builtins.__import__

        def sandbox_import(
            name: str,
            globals_: dict[str, Any] | None = None,
            locals_: dict[str, Any] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> Any:
            """Импортирует виртуальный модуль sandbox helpers или обычный Python-модуль.

            Args:
                name: Имя импортируемого модуля.
                globals_: Глобальные переменные вызывающего кода.
                locals_: Локальные переменные вызывающего кода.
                fromlist: Имена, запрошенные конструкцией ``from ... import ...``.
                level: Уровень относительного импорта.

            Returns:
                Виртуальный модуль ``functions`` или результат стандартного импорта.
            """

            if name == "functions" and level == 0:
                return helper_module
            if name == "pathlib" and level == 0:
                return pathlib_module
            return default_import(name, globals_, locals_, fromlist, level)

        sandbox_builtins = dict(vars(builtins))
        sandbox_builtins["__import__"] = sandbox_import
        sandbox_builtins["open"] = sandbox_open
        self.globals["__builtins__"] = sandbox_builtins

        try:
            import numpy as np
            import pandas as pd

            self.globals.setdefault("pd", pd)
            self.globals.setdefault("np", np)
        except Exception:
            pass


def build_python_sandbox(
    settings: AgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> DeepAgentPythonSandbox:
    """Собирает persistent runtime для tool ``python``.

    Рабочая директория — это workspace из настроек. ``readable_roots`` сохраняются
    как диагностическая информация в ответе инструмента.

    Args:
        settings: Настройки агента; если ``None`` — загружаются из JSON-конфига.
        tool_outputs_dir: Папка текущей сессии для временных/offload-артефактов; если ``None``,
            используется базовая папка из настроек.
        workspace_root: Рабочая директория агента; если ``None``, используется settings.

    Returns:
        Готовый ``DeepAgentPythonSandbox`` с seed-helpers.
    """

    from deep_agent.agent_settings import load_agent_settings

    settings = settings or load_agent_settings()
    resolved_tool_outputs_dir = (tool_outputs_dir or settings.tool_outputs_dir).resolve()
    resolved_workspace_root = (workspace_root or settings.workspace_root).resolve()
    readable_roots = (
        resolved_workspace_root,
        resolved_tool_outputs_dir,
    )
    return DeepAgentPythonSandbox(
        working_directory=resolved_workspace_root,
        readable_roots=readable_roots,
        tool_outputs_dir=resolved_tool_outputs_dir,
    )

__all__ = [
    "DeepAgentPythonSandbox",
    "SANDBOX_HELPER_NAMES",
    "build_python_sandbox",
]
