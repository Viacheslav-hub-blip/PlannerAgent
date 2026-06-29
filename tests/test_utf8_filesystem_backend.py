"""Тесты UTF-8 backend файловой системы.

Содержит:
- Utf8FilesystemBackendTests: проверки Python fallback поиска без ripgrep.
"""

from __future__ import annotations

import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from deepagents.middleware import filesystem as filesystem_middleware

from deep_agent.runtime.filesystem import (
    Utf8FilesystemBackend,
    Utf8LocalShellBackend,
    configure_read_file_default_limit,
    review_snapshot_path_for_file,
)
from deep_agent.settings import workspace_tool_path


class Utf8FilesystemBackendTests(unittest.TestCase):
    """Проверяет поиск по UTF-8 файлам при недоступном ripgrep."""

    def test_configures_builtin_read_file_default_limit(self) -> None:
        """Изменяет default ``read_file.limit`` для функции и tool schema.

        Returns:
            ``None``.
        """

        original_limit = filesystem_middleware.DEFAULT_READ_LIMIT
        original_schema_limit = (
            filesystem_middleware.ReadFileSchema.model_fields["limit"].default
        )
        try:
            configure_read_file_default_limit(500)
            middleware = filesystem_middleware.FilesystemMiddleware()
            read_file_tool = next(
                tool for tool in middleware.tools if tool.name == "read_file"
            )

            self.assertEqual(filesystem_middleware.DEFAULT_READ_LIMIT, 500)
            self.assertEqual(
                read_file_tool.args_schema.model_fields["limit"].default,
                500,
            )
        finally:
            filesystem_middleware.DEFAULT_READ_LIMIT = original_limit
            filesystem_middleware.ReadFileSchema.model_fields[
                "limit"
            ].default = original_schema_limit
            filesystem_middleware.ReadFileSchema.model_rebuild(force=True)

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

    def test_read_accepts_workspace_root_alias_and_virtual_root(self) -> None:
        """Читает один файл по каноническому ``/`` и ОС-алиасу workspace.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            file_path = root / "deep_agent" / "note.txt"
            file_path.parent.mkdir(parents=True)
            file_path.write_text("same file\n", encoding="utf-8")
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            virtual_result = backend.read("/deep_agent/note.txt")
            alias_result = backend.read(f"{root.as_posix()}/deep_agent/note.txt")

        self.assertIsNone(virtual_result.error)
        self.assertIsNone(alias_result.error)
        self.assertIsNotNone(virtual_result.file_data)
        self.assertIsNotNone(alias_result.file_data)
        self.assertEqual(virtual_result.file_data["content"], "same file\n")
        self.assertEqual(alias_result.file_data["content"], "same file\n")

    def test_read_ipynb_forces_conversion_to_percent_script(self) -> None:
        """Конвертирует ``.ipynb`` в ``.py`` перед чтением через backend.

        Returns:
            ``None``. Тест подтверждает, что ``read_file`` получает percent-script,
            а не сырой JSON notebook.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            notebook_path = root / "analysis.ipynb"
            script_path = root / "analysis.py"
            notebook_path.write_text(
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "markdown",
                                "metadata": {},
                                "source": ["# Заголовок\n"],
                            },
                            {
                                "cell_type": "code",
                                "execution_count": 1,
                                "metadata": {},
                                "outputs": [{"output_type": "stream", "text": ["4\n"]}],
                                "source": ["value = 2 + 2\n", "print(value)\n"],
                            },
                        ],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.read("/analysis.ipynb")
            script_exists = script_path.exists()
            script_text = script_path.read_text(encoding="utf-8")

        self.assertIsNone(result.error)
        self.assertTrue(script_exists)
        self.assertIsNotNone(result.file_data)
        self.assertEqual(result.file_data["encoding"], "utf-8")
        self.assertIn("# %% [markdown]\n", result.file_data["content"])
        self.assertIn("value = 2 + 2\n", result.file_data["content"])
        self.assertNotIn('"cells"', result.file_data["content"])
        self.assertEqual(result.file_data["content"], script_text)

    def test_write_overwrites_existing_file(self) -> None:
        """``write`` должен перезаписывать существующий файл тем же путем.

        Returns:
            ``None``. Тест подтверждает, что ``write_file`` не вынуждает агента
            создавать дубликаты с новыми именами.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "summary.md"
            file_path.write_text("old\n", encoding="utf-8")
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.write("/summary.md", "new\n")
            saved_content = file_path.read_text(encoding="utf-8")

        self.assertIsNone(result.error)
        self.assertEqual(result.path, "/summary.md")
        self.assertEqual(saved_content, "new\n")

    def test_write_creates_review_snapshot_once(self) -> None:
        """Сохраняет исходную версию файла перед первой записью.

        Returns:
            ``None``. Тест подтверждает, что snapshot не перезаписывается
            последующими изменениями того же файла.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            file_path = root / "module.py"
            file_path.write_text("old\n", encoding="utf-8")
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            first_result = backend.write("/module.py", "new\n")
            second_result = backend.write("/module.py", "newer\n")
            snapshot_text = review_snapshot_path_for_file(file_path, root).read_text(
                encoding="utf-8",
            )

        self.assertIsNone(first_result.error)
        self.assertIsNone(second_result.error)
        self.assertEqual(snapshot_text, "old\n")

    def test_edit_creates_review_snapshot_before_change(self) -> None:
        """Сохраняет исходную версию файла перед точечным редактированием.

        Returns:
            ``None``. Тест подтверждает, что snapshot содержит текст до замены.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            file_path = root / "module.py"
            file_path.write_text("value = 1\n", encoding="utf-8")
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.edit("/module.py", "value = 1", "value = 2")
            edited_text = file_path.read_text(encoding="utf-8")
            snapshot_text = review_snapshot_path_for_file(file_path, root).read_text(
                encoding="utf-8",
            )

        self.assertIsNone(result.error)
        self.assertEqual(result.occurrences, 1)
        self.assertEqual(edited_text, "value = 2\n")
        self.assertEqual(snapshot_text, "value = 1\n")

    def test_write_ipynb_returns_convert_warning(self) -> None:
        """Запрещает прямую запись ``.ipynb`` через ``write_file``.

        Returns:
            ``None``. Тест подтверждает, что notebook не создается, а агент
            получает предупреждение про специализированный инструмент convert.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notebook_path = root / "analysis.ipynb"
            backend = Utf8FilesystemBackend(root_dir=root, virtual_mode=True)

            result = backend.write("/analysis.ipynb", "{}")
            output_exists = notebook_path.exists()

        self.assertIsNotNone(result.error)
        self.assertIn("Предупреждение", result.error)
        self.assertIn("convert_jupyter_notebook", result.error)
        self.assertFalse(output_exists)

    def test_workspace_tool_path_uses_virtual_root(self) -> None:
        """Возвращает workspace-путь относительно виртуального ``/``.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            file_path = root / "deep_agent" / "skills" / "SKILL.md"

            result = workspace_tool_path(file_path, root)

        self.assertEqual(result, "/deep_agent/skills/SKILL.md")

    def test_execute_maps_quoted_workspace_path_with_space(self) -> None:
        """Проверяет shell-доступ к файлу по виртуальному workspace-пути с пробелом.

        Returns:
            ``None``. Тест подтверждает, что ``execute`` видит тот же файл, что и ``ls``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notebook_path = root / "VLM PRES.ipynb"
            notebook_path.write_text("notebook", encoding="utf-8")
            backend = Utf8LocalShellBackend(root_dir=root, virtual_mode=True)

            result = backend.execute(
                f'"{sys.executable}" -c "import pathlib, sys; print(pathlib.Path(sys.argv[1]).read_text())" "/VLM PRES.ipynb"'
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("notebook", result.output)

    def test_execute_maps_workspace_output_path_when_parent_exists(self) -> None:
        """Проверяет запись нового файла по виртуальному workspace-пути.

        Returns:
            ``None``. Тест подтверждает, что output path внутри workspace тоже маппится.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backend = Utf8LocalShellBackend(root_dir=root, virtual_mode=True)

            result = backend.execute(
                f'"{sys.executable}" -c "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(\'ok\', encoding=\'utf-8\')" "/created file.txt"'
            )
            created_text = (root / "created file.txt").read_text(encoding="utf-8")

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(created_text, "ok")

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
                    "path": workspace_tool_path(fields_path, root),
                    "line": 3,
                    "text": "- `age_category` - возрастная категория.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
