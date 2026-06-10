"""Persistent Python sandbox для DeepAgent с helpers чтения pickle и файлов.

Содержит:
- DeepAgentPythonSandbox: persistent sandbox для выполнения аналитического Python-кода.
- build_python_sandbox: фабрика sandbox с разрешенными директориями.
- _is_relative_to: проверка вложенности пути.
"""

from __future__ import annotations

import builtins
import pickle
import types
from pathlib import Path
from typing import Any

from deep_agent_test.core.settings import DeepAgentSettings

SANDBOX_HELPER_NAMES = frozenset(
    {
        "PROJECT_ROOT",
        "TOOL_OUTPUTS_DIR",
        "read_pickle_file",
        "describe_pickle_file",
        "rows_to_dataframe",
    }
)


class DeepAgentPythonSandbox:
    """In-memory sandbox с общими переменными между вызовами ``execute_python_code``."""

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
            readable_roots: Директории, из которых helpers разрешают чтение файлов.
            tool_outputs_dir: Папка spill-файлов (`.pkl`) после offload middleware.
        """

        self.working_directory = working_directory.resolve()
        self.readable_roots = tuple(path.resolve() for path in readable_roots)
        self.tool_outputs_dir = tool_outputs_dir.resolve()
        self.globals: dict[str, Any] = {}
        self.last_target_variable: str | None = None
        self.last_dataframe_variable: str | None = None
        self._seed_helpers()

    def _seed_helpers(self) -> None:
        """Заполняет ``globals`` helpers чтения pickle и библиотеками pandas/numpy.

        Добавляет ``PROJECT_ROOT``, ``TOOL_OUTPUTS_DIR``, ``read_pickle_file``,
        ``describe_pickle_file``, ``rows_to_dataframe`` и (если доступны) ``pd``/``np``.
        Чтение файлов ограничено разрешёнными директориями ``readable_roots``.
        """

        readable_roots = self.readable_roots
        tool_outputs_dir = self.tool_outputs_dir
        project_root = self.working_directory

        def _assert_readable_path(path: Path) -> Path:
            """Проверяет, что путь существует и лежит в разрешённых для чтения корнях."""

            resolved = path.expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Файл не найден: {resolved}")
            if not any(_is_relative_to(resolved, root) for root in readable_roots):
                allowed = ", ".join(str(root) for root in readable_roots)
                raise PermissionError(
                    f"Чтение файла запрещено вне разрешенных директорий. "
                    f"Путь: {resolved}. Разрешено: {allowed}"
                )
            return resolved

        def read_pickle_file(file_path: str) -> Any:
            """Читает pickle-файл по абсолютному или относительному пути."""

            path = _assert_readable_path(Path(file_path))
            with path.open("rb") as file:
                return pickle.load(file)

        def describe_pickle_file(file_path: str) -> dict[str, Any]:
            """Возвращает компактное описание содержимого pickle без полной загрузки в память агента."""

            data = read_pickle_file(file_path)
            description: dict[str, Any] = {
                "file_path": str(_assert_readable_path(Path(file_path))),
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

        self.globals.update(
            {
                "PROJECT_ROOT": str(project_root),
                "TOOL_OUTPUTS_DIR": str(tool_outputs_dir),
                "read_pickle_file": read_pickle_file,
                "describe_pickle_file": describe_pickle_file,
                "rows_to_dataframe": rows_to_dataframe,
            }
        )
        helper_module = types.ModuleType("functions")
        for helper_name in SANDBOX_HELPER_NAMES:
            setattr(helper_module, helper_name, self.globals[helper_name])

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
            return default_import(name, globals_, locals_, fromlist, level)

        sandbox_builtins = dict(vars(builtins))
        sandbox_builtins["__import__"] = sandbox_import
        self.globals["__builtins__"] = sandbox_builtins

        try:
            import numpy as np
            import pandas as pd

            self.globals.setdefault("pd", pd)
            self.globals.setdefault("np", np)
        except Exception:
            pass


def build_python_sandbox(
    settings: DeepAgentSettings | None = None,
    tool_outputs_dir: Path | None = None,
    workspace_root: Path | None = None,
) -> DeepAgentPythonSandbox:
    """Собирает persistent sandbox для ``execute_python_code``.

    Рабочая директория и разрешённые для чтения корни — это workspace и папка
    spill-файлов из настроек.

    Args:
        settings: Настройки агента; если ``None`` — загружаются из JSON-конфига.
        tool_outputs_dir: Папка текущей сессии для сохранения артефактов; если ``None``,
            используется базовая папка из настроек.
        workspace_root: Рабочая директория агента; если ``None``, используется settings.

    Returns:
        Готовый ``DeepAgentPythonSandbox`` с seed-helpers.
    """

    from deep_agent_test.core.settings import load_deep_agent_settings

    settings = settings or load_deep_agent_settings()
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


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Возвращает True, если ``path`` находится внутри ``parent`` (совместимо с <3.9)."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


__all__ = [
    "DeepAgentPythonSandbox",
    "SANDBOX_HELPER_NAMES",
    "build_python_sandbox",
]
