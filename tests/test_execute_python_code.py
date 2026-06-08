"""Тесты политики и компактной обработки ошибок execute_python_code.

Содержит:
- ExecutePythonCodeTests: проверки импорта helpers, запрета удаления и формата ошибок.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deep_agent_test.core.python_sandbox import DeepAgentPythonSandbox
from deep_agent_test.tools.execute_python_code import (
    EXECUTE_PYTHON_CODE_DESCRIPTION,
    build_execute_python_code_tool,
)


class ExecutePythonCodeTests(unittest.TestCase):
    def test_description_shows_session_artifact_path_example(self) -> None:
        """Проверяет наличие корректного примера сохранения артефакта в session-каталог.

        Args:
            Отсутствуют.

        Returns:
            ``None``. Тест завершается успешно, если описание содержит безопасный шаблон пути.
        """

        self.assertIn(
            'output_path = Path(TOOL_OUTPUTS_DIR) / "hits_age_category_jan2026.png"',
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "do not use `/tool_outputs` as a local Python path",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )

    """Проверяет импорт sandbox helpers и компактный формат ошибок инструмента."""

    def test_functions_import_uses_sandbox_helpers(self) -> None:
        """Проверяет импорт helpers через виртуальный модуль functions.

        Returns:
            ``None``; тест проверяет успешное выполнение и значение переменной.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=root,
            )
            tool = build_execute_python_code_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from functions import rows_to_dataframe\n"
                            "result = rows_to_dataframe([{'value': 1}]).shape[0]"
                        ),
                        "target_variable": "result",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("value:\n1", payload["variable_preview"])

    def test_runtime_error_contains_only_short_error(self) -> None:
        """Проверяет удаление traceback и служебных полей из ошибки.

        Returns:
            ``None``; тест сравнивает полный JSON-ответ инструмента.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=root,
            )
            tool = build_execute_python_code_tool(sandbox)

            error = tool.invoke({"code": "raise ValueError('bad input')"})

        self.assertEqual(error, "ValueError: bad input")

    def test_remove_call_remains_forbidden(self) -> None:
        """Проверяет сохранение запрета на удаление файлов.

        Returns:
            ``None``; тест проверяет краткую ошибку статической политики.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=root,
            )
            tool = build_execute_python_code_tool(sandbox)

            error = tool.invoke({"code": "import os\nos.remove('data.pkl')"})

        self.assertEqual(
            error,
            "ValueError: Call 'os.remove' is not allowed in execute_python_code",
        )

    def test_remove_call_through_import_alias_remains_forbidden(self) -> None:
        """Проверяет запрет удаления через алиас импортированного модуля.

        Returns:
            ``None``; тест проверяет нормализованное имя запрещенного вызова.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=root,
            )
            tool = build_execute_python_code_tool(sandbox)

            error = tool.invoke({"code": "import os as system_os\nsystem_os.remove('data.pkl')"})

        self.assertEqual(
            error,
            "ValueError: Call 'os.remove' is not allowed in execute_python_code",
        )


if __name__ == "__main__":
    unittest.main()
