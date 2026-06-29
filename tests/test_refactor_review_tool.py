"""Тесты внутреннего инструмента ревью рефакторинга.

Содержит:
- RefactorReviewToolTests: проверки сборки tool без запуска модели.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deep_agent.tools.refactor_review import (
    REVIEW_REFACTOR_TOOL_NAME,
    build_review_refactor_tool,
)


class RefactorReviewToolTests(unittest.TestCase):
    """Проверяет минимальную сборку внутреннего review tool."""

    def test_builds_review_refactor_tool(self) -> None:
        """Создает tool с ожидаемым именем и схемой аргументов.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            tool = build_review_refactor_tool(
                model=object(),
                workspace_root=Path(temp_dir),
            )

        self.assertEqual(tool.name, REVIEW_REFACTOR_TOOL_NAME)
        self.assertIn("user_request", tool.args_schema.model_fields)
        self.assertIn("edited_path", tool.args_schema.model_fields)


if __name__ == "__main__":
    unittest.main()
