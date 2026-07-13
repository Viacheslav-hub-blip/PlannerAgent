"""Backend файловой системы и локального shell для единого workspace.

Содержит:
- configure_read_file_default_limit: настройка default limit встроенного ``read_file``.
- WorkspaceFilesystemMixin: пути, запись файлов/notebook и review snapshots.
- WorkspaceReadMixin: чтение notebook и явная пометка неполной страницы.
- Utf8FilesystemBackend: локальное расширение ``FilesystemBackend`` с явным чтением UTF-8.
- Utf8LocalShellBackend: локальный shell backend рабочего workspace с UTF-8 поиском.
- _converted_notebook_script_path: путь percent-script для принудительного чтения notebook.
- _has_more_text_lines: проверка наличия строк за пределами прочитанной страницы.
- _append_incomplete_read_notice: добавление предупреждения о неполном чтении.
- review_snapshot_path_for_file: путь snapshot исходника для внутреннего ревью.
- _save_review_snapshot_if_needed: сохранение первой версии файла перед правкой.
- _rewrite_workspace_paths_in_shell_command: перенос виртуальных workspace-путей в реальные shell-пути.
- _workspace_shell_path: преобразование одного workspace-пути для shell-команды.
- _quote_shell_path: безопасное quoting пути для shell-команды.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from deepagents.backends import FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import EditResult, ReadResult, WriteResult

from deep_agent.agent_settings import (
    strip_workspace_tool_prefix,
    workspace_tool_root,
)
from deep_agent.tools.jupyter_notebook_tool import (
    build_notebook_from_python_text,
    convert_jupyter_notebook_file,
)

REVIEW_SNAPSHOT_DIR = ".deep_agent/review_snapshots"
NOTEBOOK_SCRIPT_CACHE_DIR = ".deep_agent/notebook_scripts"


def configure_read_file_default_limit(limit: int) -> None:
    """Настраивает число строк встроенного инструмента ``read_file`` по умолчанию.

    DeepAgents не предоставляет публичный параметр для изменения default значения
    ``limit``. Настройка применяется до создания ``FilesystemMiddleware`` и меняет
    одновременно default функции и Pydantic-схемы инструмента.

    Args:
        limit: Положительное число строк, читаемых при отсутствии аргумента ``limit``.

    Returns:
        ``None``.

    Raises:
        ValueError: Передано неположительное значение.
    """

    if limit <= 0:
        raise ValueError("read_file_default_limit должен быть положительным.")

    from deepagents.middleware import filesystem as filesystem_middleware

    filesystem_middleware.DEFAULT_READ_LIMIT = limit
    filesystem_middleware.ReadFileSchema.model_fields["limit"].default = limit
    filesystem_middleware.ReadFileSchema.model_rebuild(force=True)


class WorkspaceFilesystemMixin:
    """Добавляет backend единые workspace-пути, запись notebook и review snapshots.

    Args:
        *args: Позиционные аргументы базового backend.
        **kwargs: Именованные аргументы базового backend.

    Returns:
        Backend, который принимает пути ``/home/user/project/file`` и возвращает
        такие же полные пути в результатах ``ls``, ``glob`` и ``grep``.
    """

    tool_path_root: str

    def __init__(self, *args, **kwargs) -> None:
        """Инициализирует базовый backend и сохраняет полный tool-префикс workspace.

        Args:
            *args: Позиционные аргументы базового backend.
            **kwargs: Именованные аргументы базового backend.

        Returns:
            ``None``.
        """

        super().__init__(*args, **kwargs)
        self.tool_path_root = workspace_tool_root(self.cwd)

    def _resolve_path(self, key: str) -> Path:
        """Преобразует полный workspace-путь в путь виртуального backend.

        Args:
            key: Путь из filesystem tool.

        Returns:
            Реальный локальный путь, разрешённый базовым backend.
        """

        return super()._resolve_path(self._strip_workspace_prefix(key))

    def _to_virtual_path(self, path: Path) -> str:
        """Преобразует реальный путь в полный workspace-путь tools.

        Args:
            path: Реальный локальный путь внутри workspace.

        Returns:
            Полный POSIX-путь с префиксом настроенного workspace.
        """

        relative_path = path.resolve().relative_to(self.cwd).as_posix()
        if not relative_path:
            return self.tool_path_root
        base = self.tool_path_root.rstrip("/")
        return f"{base}/{relative_path}" if base else f"/{relative_path}"

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Записывает текстовый файл, создавая новый или перезаписывая существующий.

        Args:
            file_path: Виртуальный путь файла внутри workspace. Для ``.ipynb``
                текст преобразуется в notebook через логику ``convert_jupyter_notebook``.
            content: Полное текстовое содержимое, которое нужно сохранить.

        Returns:
            ``WriteResult`` с путем при успешной записи или текстом ошибки при сбое.
        """

        try:
            resolved_path = self._resolve_path(file_path)
        except (OSError, RuntimeError) as error:
            return WriteResult(error=f"Error writing file '{file_path}': {error}")

        if resolved_path.suffix.lower() == ".ipynb":
            return self._write_notebook(file_path, resolved_path, content)

        try:
            _save_review_snapshot_if_needed(resolved_path, self.cwd)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(resolved_path, flags, 0o644)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
                file.write(content)
            return WriteResult(path=file_path)
        except (OSError, UnicodeEncodeError) as error:
            return WriteResult(error=f"Error writing file '{file_path}': {error}")

    def _write_notebook(
        self,
        file_path: str,
        resolved_path: Path,
        content: str,
    ) -> WriteResult:
        """Создает ``.ipynb`` из текста, переданного в ``write_file``.

        Args:
            file_path: Исходный виртуальный путь из вызова ``write_file``.
            resolved_path: Разрешенный локальный путь notebook внутри workspace.
            content: Текст Python/percent-script для преобразования в notebook.

        Returns:
            ``WriteResult`` с путем при успешной записи или текстом ошибки при сбое.
        """

        try:
            notebook = build_notebook_from_python_text(
                content,
                split_comment_markdown=True,
            )
            _save_review_snapshot_if_needed(resolved_path, self.cwd)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(
                json.dumps(notebook, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="",
            )
            return WriteResult(path=file_path)
        except (OSError, UnicodeEncodeError, ValueError) as error:
            return WriteResult(error=f"Error writing notebook '{file_path}': {error}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Редактирует файл, сохраняя snapshot исходной версии перед первой правкой.

        Args:
            file_path: Виртуальный путь редактируемого файла внутри workspace.
            old_string: Точный фрагмент для замены.
            new_string: Новый фрагмент.
            replace_all: Нужно ли заменить все найденные вхождения.

        Returns:
            ``EditResult`` базового backend с числом замен или текстом ошибки.
        """

        try:
            resolved_path = self._resolve_path(file_path)
        except (OSError, RuntimeError) as error:
            return EditResult(error=f"Error editing file '{file_path}': {error}")

        try:
            _save_review_snapshot_if_needed(resolved_path, self.cwd)
        except OSError as error:
            return EditResult(error=f"Error creating review snapshot for '{file_path}': {error}")

        return super().edit(
            file_path,
            old_string,
            new_string,
            replace_all=replace_all,
        )

    def _strip_workspace_prefix(self, key: str) -> str:
        """Удаляет полный workspace-префикс перед передачей пути в virtual backend.

        Args:
            key: Путь из filesystem tool.

        Returns:
            Путь относительно виртуального корня backend.
        """

        relative_path = strip_workspace_tool_prefix(str(key or ""), self.cwd)
        if relative_path is None:
            return key
        if not relative_path:
            return "/"
        return f"/{relative_path}"


class WorkspaceReadMixin(WorkspaceFilesystemMixin):
    """Добавляет backend чтение notebook и контроль пагинации текстовых файлов.

    Args:
        *args: Позиционные аргументы, передаваемые в базовый ``FilesystemBackend``.
        **kwargs: Именованные аргументы, передаваемые в базовый ``FilesystemBackend``.

    Returns:
        Экземпляр backend с единым чтением текстовых файлов и notebook.
    """

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ):
        """Читает страницу файла и явно сообщает о наличии продолжения.

        Args:
            file_path: Абсолютный виртуальный путь к файлу. Для ``.ipynb`` сначала
                принудительно создается ``.py`` percent-script через tool конвертации.
            offset: Смещение первой читаемой строки, начиная с нуля.
            limit: Максимальное число строк содержимого в одной странице.

        Returns:
            Результат чтения backend. Для ``.ipynb`` возвращается содержимое
            сконвертированного ``.py`` файла, а не сырой JSON notebook.
        """

        read_path = file_path
        try:
            resolved_path = self._resolve_path(file_path)
        except (OSError, RuntimeError) as error:
            return ReadResult(error=f"Error reading file '{file_path}': {error}")
        read_resolved_path = resolved_path

        if resolved_path.suffix.lower() == ".ipynb":
            output_path = _converted_notebook_script_path(resolved_path, self.cwd)
            try:
                convert_jupyter_notebook_file(
                    mode="ipynb_to_py",
                    source_path=self._to_virtual_path(resolved_path),
                    output_path=self._to_virtual_path(output_path),
                    workspace_root=self.cwd,
                    overwrite=True,
                )
            except (OSError, ValueError, RuntimeError) as error:
                return ReadResult(
                    error=(
                        f"Error converting notebook '{file_path}' before read_file: "
                        f"{error}"
                    )
                )
            read_path = self._to_virtual_path(output_path)
            read_resolved_path = output_path

        result = super().read(read_path, offset=offset, limit=limit)
        if result.error or result.file_data is None:
            return result
        if result.file_data.get("encoding") != "utf-8":
            return result

        next_offset = offset + limit
        if _has_more_text_lines(read_resolved_path, next_offset):
            _append_incomplete_read_notice(result, next_offset)
        return result

class Utf8FilesystemBackend(WorkspaceReadMixin, FilesystemBackend):
    """FilesystemBackend с workspace paths, notebook read/write и pagination."""


class Utf8LocalShellBackend(WorkspaceReadMixin, LocalShellBackend):
    """LocalShellBackend рабочего workspace с notebook support и path rewrite."""

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ):
        """Выполняет shell-команду с преобразованием виртуальных workspace-путей.

        Args:
            command: Команда shell, где пути вида ``/file.txt`` относятся к workspace.
            timeout: Максимальное время выполнения команды в секундах.

        Returns:
            Результат выполнения команды из базового ``LocalShellBackend``.
        """

        rewritten_command = _rewrite_workspace_paths_in_shell_command(command, self.cwd)
        return super().execute(rewritten_command, timeout=timeout)


def _converted_notebook_script_path(notebook_path: Path, workspace_root: Path) -> Path:
    """Возвращает путь ``.py`` percent-script для notebook.

    Args:
        notebook_path: Реальный путь к ``.ipynb`` файлу внутри workspace.
        workspace_root: Корень workspace, внутри которого хранится служебный cache.

    Returns:
        Реальный путь к служебному ``.py`` файлу с тем же stem внутри ``.deep_agent``.
    """

    root = workspace_root.resolve()
    try:
        relative_notebook_path = notebook_path.resolve().relative_to(root)
    except ValueError:
        relative_notebook_path = Path(notebook_path.name)
    return root / NOTEBOOK_SCRIPT_CACHE_DIR / relative_notebook_path.with_suffix(".py")


def _has_more_text_lines(file_path: Path, next_offset: int) -> bool:
    """Проверяет, есть ли в UTF-8 файле строки после прочитанной страницы.

    Args:
        file_path: Реальный путь к текстовому файлу.
        next_offset: Нулевой номер первой строки следующей страницы.

    Returns:
        ``True``, если после ``next_offset`` есть хотя бы одна строка.
    """

    try:
        with file_path.open("r", encoding="utf-8") as file:
            for line_number, _ in enumerate(file):
                if line_number >= next_offset:
                    return True
    except (OSError, UnicodeDecodeError):
        return False
    return False


def _append_incomplete_read_notice(result: ReadResult, next_offset: int) -> None:
    """Добавляет в ``read_file`` явное предупреждение о неполном чтении.

    Args:
        result: Результат чтения файла, который нужно дополнить предупреждением.
        next_offset: Значение ``offset`` для следующего вызова ``read_file``.

    Returns:
        ``None``. Содержимое ``result.file_data`` изменяется на месте.
    """

    if result.file_data is None:
        return
    content = str(result.file_data.get("content") or "")
    if content and not content.endswith(("\n", "\r")):
        content += "\n"
    result.file_data["content"] = (
        content
        + f"[Файл прочитан не полностью; продолжите чтение с offset={next_offset}.]"
    )


def review_snapshot_path_for_file(file_path: str | Path, workspace_root: Path) -> Path:
    """Возвращает путь snapshot исходной версии файла для внутреннего ревью.

    Args:
        file_path: Реальный путь файла внутри workspace.
        workspace_root: Корень workspace.

    Returns:
        Реальный путь snapshot-файла внутри ``.deep_agent/review_snapshots``.

    Raises:
        ValueError: Файл находится вне workspace.
    """

    root = workspace_root.resolve()
    resolved_path = Path(file_path).expanduser().resolve()
    relative_path = resolved_path.relative_to(root)
    snapshot_name = f"{relative_path.name}.original"
    return root / REVIEW_SNAPSHOT_DIR / relative_path.parent / snapshot_name


def _save_review_snapshot_if_needed(file_path: Path, workspace_root: Path) -> None:
    """Сохраняет первую версию существующего файла перед записью или редактированием.

    Args:
        file_path: Реальный путь файла, который будет изменен.
        workspace_root: Корень workspace.

    Returns:
        ``None``. Snapshot создается только один раз и не перезаписывается.
    """

    if not file_path.exists() or not file_path.is_file():
        return

    snapshot_path = review_snapshot_path_for_file(file_path, workspace_root)
    if snapshot_path.exists():
        return

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(file_path.read_bytes())


def _rewrite_workspace_paths_in_shell_command(command: str, workspace_root: Path) -> str:
    """Переписывает виртуальные workspace-пути внутри shell-команды в реальные ОС-пути.

    Args:
        command: Исходная shell-команда от агента.
        workspace_root: Реальный корень workspace, где выполняется shell.

    Returns:
        Команда, в которой существующие или создаваемые workspace-пути вида
        ``/file.txt`` заменены на абсолютные ОС-пути внутри ``workspace_root``.
    """

    text = str(command or "")
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in {"'", '"'}:
            quote = char
            end = index + 1
            escaped = False
            while end < len(text):
                current = text[end]
                if current == "\\" and quote == '"' and not escaped:
                    escaped = True
                    end += 1
                    continue
                if current == quote and not escaped:
                    break
                escaped = False
                end += 1
            if end >= len(text):
                result.append(text[index:])
                break
            raw_value = text[index + 1 : end]
            mapped_value = _workspace_shell_path(raw_value, workspace_root)
            if mapped_value is None:
                result.append(text[index : end + 1])
            else:
                escaped_value = mapped_value.replace("\\", "\\\\") if quote == '"' else mapped_value
                escaped_value = escaped_value.replace(quote, f"\\{quote}")
                result.append(f"{quote}{escaped_value}{quote}")
            index = end + 1
            continue

        if char.isspace() or char in "|&;<>()":
            result.append(char)
            index += 1
            continue

        end = index
        while end < len(text) and not text[end].isspace() and text[end] not in "|&;<>()":
            end += 1
        token = text[index:end]
        mapped_token = _workspace_shell_path(token, workspace_root)
        result.append(_quote_shell_path(mapped_token) if mapped_token is not None else token)
        index = end
    return "".join(result)


def _workspace_shell_path(value: str, workspace_root: Path) -> str | None:
    """Преобразует один виртуальный workspace-путь в реальный путь для shell.

    Args:
        value: Токен или значение внутри кавычек из shell-команды.
        workspace_root: Реальный корень workspace.

    Returns:
        Абсолютный POSIX-путь внутри workspace или ``None``, если значение не похоже
        на workspace-путь.
    """

    relative_path = strip_workspace_tool_prefix(value, workspace_root)
    if relative_path is None:
        return None
    candidate = workspace_root.resolve() if not relative_path else (workspace_root / relative_path).resolve()
    try:
        candidate.relative_to(workspace_root.resolve())
    except ValueError:
        return None
    if candidate.exists() or candidate.parent.exists():
        return candidate.as_posix()
    return None


def _quote_shell_path(path: str) -> str:
    """Экранирует путь для shell-команды, если он был вне кавычек.

    Args:
        path: Реальный путь к файлу или директории.

    Returns:
        Shell-safe представление пути.
    """

    return shlex.quote(path)


__all__ = [
    "Utf8FilesystemBackend",
    "Utf8LocalShellBackend",
    "WorkspaceFilesystemMixin",
    "WorkspaceReadMixin",
    "configure_read_file_default_limit",
    "review_snapshot_path_for_file",
]
