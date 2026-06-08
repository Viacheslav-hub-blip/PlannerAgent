"""Backend файловой системы с UTF-8 fallback-поиском.

Содержит:
- Utf8FilesystemBackend: локальное расширение ``FilesystemBackend`` с явным чтением UTF-8.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import wcmatch.glob as wcglob
from deepagents.backends import FilesystemBackend

logger = logging.getLogger(__name__)


class Utf8FilesystemBackend(FilesystemBackend):
    """FilesystemBackend с явной UTF-8 кодировкой для Python fallback grep.

    Args:
        *args: Позиционные аргументы, передаваемые в базовый ``FilesystemBackend``.
        **kwargs: Именованные аргументы, передаваемые в базовый ``FilesystemBackend``.

    Returns:
        Экземпляр backend, совместимый с ``FilesystemBackend``.
    """

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
