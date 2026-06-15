"""Тесты UTF-8 backend файловой системы.

Содержит:
- Utf8FilesystemBackendTests: проверки Python fallback поиска без ripgrep.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deep_agent.runtime.filesystem import Utf8FilesystemBackend


class Utf8FilesystemBackendTests(unittest.TestCase):
    """Проверяет поиск по UTF-8 файлам при недоступном ripgrep."""

    def test_read_marks_incomplete_page_with_next_offset(self) -> None:
        """Добавляет маркер продолжения, если после страницы остались строки.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "large.txt").write_text(
                "line 1\nline 2\nline 3\n",
                encoding="utf-8",
            )
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.read("/large.txt", offset=0, limit=2)

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.file_data)
        content = result.file_data["content"]
        self.assertIn("line 1\nline 2\n", content)
        self.assertIn("Файл прочитан не полностью", content)
        self.assertIn("offset=2", content)

    def test_read_does_not_mark_complete_page(self) -> None:
        """Не добавляет маркер, если файл заканчивается на границе страницы.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "complete.txt").write_text(
                "line 1\nline 2\n",
                encoding="utf-8",
            )
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.read("/complete.txt", offset=0, limit=2)

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.file_data)
        self.assertEqual(result.file_data["content"], "line 1\nline 2\n")

    def test_python_fallback_reads_utf8_explicitly(self) -> None:
        """Находит ASCII-поле в UTF-8 файле с русским текстом без использования ripgrep.

        Args:
            Отсутствуют.

        Returns:
            ``None``. Тест завершается успешно, если fallback возвращает совпадение.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fields_path = root / "hit-table" / "fields.md"
            fields_path.parent.mkdir(parents=True)
            fields_path.write_text(
                "# Поля hits\n\n- `age_category` - возрастная категория.\n",
                encoding="utf-8",
            )
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            with patch.object(backend, "_ripgrep_search", return_value=None):
                result = backend.grep(
                    pattern="age_category",
                    path="/hit-table",
                    glob="fields.md",
                )

        self.assertIsNone(result.error)
        self.assertEqual(
            result.matches,
            [
                {
                    "path": "/hit-table/fields.md",
                    "line": 3,
                    "text": "- `age_category` - возрастная категория.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
