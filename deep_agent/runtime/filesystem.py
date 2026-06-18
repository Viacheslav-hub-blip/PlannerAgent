"""Backend файловой системы и локального shell с UTF-8 fallback-поиском.

Содержит:
- configure_read_file_default_limit: настройка default limit встроенного ``read_file``.
- WorkspacePathPrefixMixin: единое отображение полного workspace-префикса в tools.
- Utf8SearchMixin: общий UTF-8 fallback-поиск для локальных backend.
- Utf8FilesystemBackend: локальное расширение ``FilesystemBackend`` с явным чтением UTF-8.
- Utf8LocalShellBackend: локальный shell backend рабочего workspace с UTF-8 поиском.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import wcmatch.glob as wcglob
from deepagents.backends import FilesystemBackend, LocalShellBackend

from deep_agent.settings import workspace_tool_root

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

    def _strip_workspace_prefix(self, key: str) -> str:
        """Удаляет полный workspace-префикс перед передачей пути в virtual backend.

        Args:
            key: Путь из filesystem tool.

        Returns:
            Путь относительно виртуального корня backend.
        """

        normalized = str(key or "").replace("\\", "/")
        prefix = self.tool_path_root.rstrip("/")
        if prefix and prefix != "/" and normalized == prefix:
            return "/"
        if prefix and prefix != "/" and normalized.startswith(f"{prefix}/"):
            suffix = normalized[len(prefix) :].lstrip("/")
            return f"/{suffix}" if suffix else "/"
        return key


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
            file_path: Абсолютный виртуальный путь к файлу.
            offset: Смещение первой читаемой строки, начиная с нуля.
            limit: Максимальное число строк содержимого в одной странице.

        Returns:
            Результат чтения backend с маркером следующего ``offset``, если
            файл не закончился на текущей странице.
        """

        result = super().read(file_path, offset=offset, limit=limit + 1)
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
    """LocalShellBackend рабочего workspace с UTF-8 fallback grep."""


__all__ = [
    "Utf8FilesystemBackend",
    "Utf8LocalShellBackend",
    "Utf8SearchMixin",
    "WorkspacePathPrefixMixin",
    "configure_read_file_default_limit",
]
