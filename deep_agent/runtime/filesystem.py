"""Backend файловой системы и локального shell с UTF-8 fallback-поиском.

Содержит:
- configure_read_file_default_limit: настройка default limit встроенного ``read_file``.
- WorkspacePathPrefixMixin: единое отображение полного workspace-префикса в tools.
- WorkspacePathPrefixMixin.write: запись текстового файла с разрешенной перезаписью.
- Utf8SearchMixin: общий UTF-8 fallback-поиск для локальных backend.
- Utf8FilesystemBackend: локальное расширение ``FilesystemBackend`` с явным чтением UTF-8.
- Utf8LocalShellBackend: локальный shell backend рабочего workspace с UTF-8 поиском.
- _converted_notebook_script_path: путь percent-script для принудительного чтения notebook.
- _rewrite_workspace_paths_in_shell_command: перенос виртуальных workspace-путей в реальные shell-пути.
- _workspace_shell_path: преобразование одного workspace-пути для shell-команды.
- _quote_shell_path: безопасное quoting пути для shell-команды.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from pathlib import Path

import wcmatch.glob as wcglob
from deepagents.backends import FilesystemBackend, LocalShellBackend
from deepagents.backends.protocol import ReadResult, WriteResult

from deep_agent.settings import strip_workspace_tool_prefix, workspace_tool_root
from deep_agent.tools.jupyter_notebook import convert_jupyter_notebook_file

logger = logging.getLogger(__name__)


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


class WorkspacePathPrefixMixin:
    """Добавляет backend полные workspace-пути в формате tools.

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
            file_path: Виртуальный путь файла внутри workspace. Прямая запись
                ``.ipynb`` запрещена: notebook нужно создавать через convert tool.
            content: Полное текстовое содержимое, которое нужно сохранить.

        Returns:
            ``WriteResult`` с путем при успешной записи или текстом ошибки при сбое.
        """

        try:
            resolved_path = self._resolve_path(file_path)
        except (OSError, RuntimeError) as error:
            return WriteResult(error=f"Error writing file '{file_path}': {error}")

        if resolved_path.suffix.lower() == ".ipynb":
            return WriteResult(
                error=(
                    "Предупреждение: write_file не записывает `.ipynb` напрямую. "
                    "Используйте специализированного агента или инструмент "
                    "convert_jupyter_notebook."
                )
            )

        try:
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


class Utf8SearchMixin(WorkspacePathPrefixMixin):
    """Добавляет backend явное чтение UTF-8 в Python fallback grep.

    Args:
        *args: Позиционные аргументы, передаваемые в базовый ``FilesystemBackend``.
        **kwargs: Именованные аргументы, передаваемые в базовый ``FilesystemBackend``.

    Returns:
        Экземпляр backend с UTF-8 fallback-поиском.
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

        if resolved_path.suffix.lower() == ".ipynb":
            output_path = _converted_notebook_script_path(resolved_path)
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

        result = super().read(read_path, offset=offset, limit=limit + 1)
        if result.error or result.file_data is None:
            return result
        if result.file_data.get("encoding") != "utf-8":
            return result

        lines = result.file_data["content"].splitlines(keepends=True)
        if len(lines) <= limit:
            return result

        page = "".join(lines[:limit])
        if page and not page.endswith(("\n", "\r")):
            page += "\n"
        next_offset = offset + limit
        result.file_data["content"] = (
            page
            + f"[Файл прочитан не полностью; продолжите чтение с offset={next_offset}.]"
        )
        return result

    def _python_search(
        self,
        pattern: str,
        base_full: Path,
        include_glob: str | None,
    ) -> tuple[dict[str, list[tuple[int, str]]], str | None]:
        """Ищет текст в файлах через Python fallback с чтением файлов как UTF-8.

        Args:
            pattern: Экранированный regex-паттерн для поиска литеральной строки.
            base_full: Абсолютный путь к директории или файлу, где выполняется поиск.
            include_glob: Необязательный glob-фильтр файлов.

        Returns:
            Кортеж из словаря совпадений и опциональной ошибки частичного обхода.
        """

        regex = re.compile(pattern)
        results: dict[str, list[tuple[int, str]]] = {}
        root = base_full if base_full.is_dir() else base_full.parent

        try:
            for fp in root.rglob("*"):
                try:
                    if not fp.is_file():
                        continue
                except (PermissionError, OSError, RuntimeError):
                    continue

                if include_glob:
                    rel_path = str(fp.relative_to(root))
                    if not wcglob.globmatch(rel_path, include_glob, flags=wcglob.BRACE | wcglob.GLOBSTAR):
                        continue

                try:
                    if fp.stat().st_size > self.max_file_size_bytes:
                        continue
                except (OSError, RuntimeError):
                    continue

                try:
                    content = fp.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError, OSError, RuntimeError):
                    continue

                for line_num, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        if self.virtual_mode:
                            try:
                                virt_path = self._to_virtual_path(fp)
                            except ValueError:
                                logger.debug("Skipping grep result outside root: %s", fp)
                                continue
                            except (OSError, RuntimeError):
                                logger.warning("Could not resolve grep result path: %s", fp, exc_info=True)
                                continue
                        else:
                            virt_path = str(fp)
                        results.setdefault(virt_path, []).append((line_num, line))
        except (OSError, RuntimeError) as exc:
            message = f"Grep of '{base_full}' aborted after {len(results)} matching file(s): {exc}"
            logger.warning("%s", message, exc_info=True)
            return results, message

        return results, None


class Utf8FilesystemBackend(Utf8SearchMixin, FilesystemBackend):
    """FilesystemBackend с явной UTF-8 кодировкой для Python fallback grep."""


class Utf8LocalShellBackend(Utf8SearchMixin, LocalShellBackend):
    """LocalShellBackend рабочего workspace с UTF-8 fallback grep и workspace path rewrite."""

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


def _converted_notebook_script_path(notebook_path: Path) -> Path:
    """Возвращает путь ``.py`` percent-script для notebook.

    Args:
        notebook_path: Реальный путь к ``.ipynb`` файлу внутри workspace.

    Returns:
        Реальный путь к ``.py`` файлу с тем же stem рядом с notebook.
    """

    return notebook_path.with_suffix(".py")


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
    "Utf8SearchMixin",
    "WorkspacePathPrefixMixin",
    "configure_read_file_default_limit",
]
