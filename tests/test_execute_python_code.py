"""Тесты полного доступа и компактной обработки ошибок execute_python_code.

Содержит:
- ExecutePythonCodeTests: проверки helpers, файлового доступа, subprocess и формата ошибок.
"""

from __future__ import annotations

import json
import pickle
import tempfile
import unittest
from pathlib import Path

from deep_agent.runtime.python_sandbox import DeepAgentPythonSandbox
from deep_agent.settings import workspace_tool_path
from deep_agent.tools.python_execution import (
    EXECUTE_PYTHON_CODE_DESCRIPTION,
    build_execute_python_code_tool,
)


class ExecutePythonCodeTests(unittest.TestCase):
    """Проверяет контракт Python execution tool с полным доступом внутри workspace."""

    def test_description_contains_policy_as_prompt_sections(self) -> None:
        """Проверяет декларативную политику выбора инструмента и примеры.

        Returns:
            ``None``. Тест завершается успешно при наличии ключевых policy-секций.
        """

        required_fragments = (
            "Предпочитай инструмент:",
            "Правило выбора:",
            "Хорошее решение:",
            "Работа с путями:",
            "Обработка ошибок:",
            "сначала выполни код",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, EXECUTE_PYTHON_CODE_DESCRIPTION)

    def test_description_shows_session_artifact_path_example(self) -> None:
        """Проверяет примеры сохранения пользовательских и временных артефактов.

        Args:
            Отсутствуют.

        Returns:
            ``None``. Тест завершается успешно, если описание содержит безопасный шаблон пути.
        """

        self.assertIn(
            'output_path = Path(WORKSPACE_ROOT) / "generated_report.json"',
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            'output_path = Path(TOOL_OUTPUTS_DIR) / "scratch.json"',
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "`target_variable` можно не передавать",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "для запрошенных пользовательских файлов используй явный путь пользователя или `Path(WORKSPACE_ROOT)`",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "для временных, промежуточных и offload-артефактов используй `Path(TOOL_OUTPUTS_DIR)`",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "для запуска shell/subprocess-команд через Python",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )
        self.assertIn(
            "для генерации и проверки алгоритмов",
            EXECUTE_PYTHON_CODE_DESCRIPTION,
        )

    def test_full_workspace_path_can_be_read_and_written(self) -> None:
        """Проверяет чтение и запись по полному workspace-пути.

        Returns:
            ``None``; тест подтверждает преобразование полного tool-пути в реальный.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_file = root / "my_notebook.ipynb"
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
                            "from pathlib import Path\n"
                            f"path = Path(r'{workspace_tool_path(workspace_file, root)}')\n"
                            "path.write_text('{\"ok\": true}', encoding='utf-8')\n"
                            "result = path.read_text(encoding='utf-8')"
                        ),
                        "target_variable": "result",
                    }
                )
            )
            written_text = workspace_file.read_text(encoding="utf-8")

        self.assertTrue(payload["success"])
        self.assertEqual(written_text, '{"ok": true}')
        self.assertIn('\\"ok\\": true', payload["variable_preview"])

    def test_open_uses_configured_tool_outputs_dir(self) -> None:
        """Проверяет запись файла в каталог артефактов из настроек sandbox.

        Returns:
            ``None``; тест подтверждает использование ``TOOL_OUTPUTS_DIR``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs_dir = root / "configured_outputs"
            outputs_dir.mkdir()
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root, outputs_dir),
                tool_outputs_dir=outputs_dir,
            )
            tool = build_execute_python_code_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from pathlib import Path\n"
                            "output_path = Path(TOOL_OUTPUTS_DIR) / 'my_notebook.ipynb'\n"
                            "with open(output_path, 'w', encoding='utf-8') as file:\n"
                            "    file.write('{}')\n"
                            "result = str(output_path)"
                        ),
                        "target_variable": "result",
                    }
                )
            )

            notebook_path = outputs_dir / "my_notebook.ipynb"
            self.assertTrue(payload["success"])
            self.assertTrue(notebook_path.exists())
        self.assertIn("configured_outputs", payload["variable_preview"])

    def test_target_variable_can_be_omitted_for_file_side_effect(self) -> None:
        """Проверяет выполнение кода без переменной результата для файлового side effect.

        Returns:
            ``None``; тест подтверждает, что ``target_variable`` не обязателен.
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
                            "from pathlib import Path\n"
                            "Path('side_effect.txt').write_text('ok', encoding='utf-8')"
                        ),
                    }
                )
            )

            side_effect_path = root / "side_effect.txt"
            side_effect_exists = side_effect_path.exists()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["target_variable"], "")
        self.assertEqual(payload["variable_preview"], "")
        self.assertTrue(side_effect_exists)

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

    def test_read_pickle_file_maps_full_workspace_path(self) -> None:
        """Проверяет чтение pickle по полному workspace-пути.

        Returns:
            ``None``; тест подтверждает преобразование полного ``workspace_file``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pickle_path = root / "runs" / "data.pkl"
            pickle_path.parent.mkdir()
            with pickle_path.open("wb") as file:
                pickle.dump([{"value": 7}], file)

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
                            "result = read_pickle_file("
                            f"r'{workspace_tool_path(pickle_path, root)}'"
                            ")"
                        ),
                        "target_variable": "result",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn('"value": 7', payload["variable_preview"])

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

        self.assertIn("ValueError: bad input", error)
        self.assertIn(
            "Попробуйте вызвать инструмент с другими параметрами или использовать другой инструмент.",
            error,
        )

    def test_subprocess_run_is_available(self) -> None:
        """Проверяет запуск subprocess из Python-кода.

        Returns:
            ``None``; тест подтверждает полный доступ к стандартному Python runtime.
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
                            "import subprocess, sys\n"
                            "completed = subprocess.run(\n"
                            "    [sys.executable, '-c', 'print(42)'],\n"
                            "    capture_output=True,\n"
                            "    text=True,\n"
                            "    check=True,\n"
                            ")\n"
                            "result = completed.stdout.strip()"
                        ),
                        "target_variable": "result",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("42", payload["variable_preview"])

    def test_remove_and_path_unlink_are_available(self) -> None:
        """Проверяет удаление файлов через ``os.remove`` и ``Path.unlink``.

        Returns:
            ``None``; тест подтверждает отсутствие статического запрета удаления.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remove_path = root / "remove.txt"
            unlink_path = root / "unlink.txt"
            remove_path.write_text("remove", encoding="utf-8")
            unlink_path.write_text("unlink", encoding="utf-8")
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
                            "import os\n"
                            "from pathlib import Path\n"
                            "os.remove('remove.txt')\n"
                            "Path('unlink.txt').unlink()\n"
                            "result = 'deleted'"
                        ),
                        "target_variable": "result",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertFalse(remove_path.exists())
        self.assertFalse(unlink_path.exists())

    def test_long_code_is_not_rejected_by_local_limit(self) -> None:
        """Проверяет, что локального лимита длины кода больше нет.

        Returns:
            ``None``; тест подтверждает выполнение кода длиннее прежнего лимита.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=root,
            )
            tool = build_execute_python_code_tool(sandbox)
            long_comment = "#" + ("x" * 55_000)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": f"{long_comment}\nresult = 123",
                        "target_variable": "result",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("123", payload["variable_preview"])


if __name__ == "__main__":
    unittest.main()
