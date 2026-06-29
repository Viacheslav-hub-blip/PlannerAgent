"""Тесты полного доступа и компактной обработки ошибок tool ``python``.

Содержит:
- PythonToolTests: проверки helpers, файлового доступа, subprocess и формата ошибок.
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
    build_python_tool,
)


class PythonToolTests(unittest.TestCase):
    """Проверяет контракт REPL tool ``python`` с полным доступом внутри workspace."""

    def test_tool_schema_has_no_target_variable(self) -> None:
        """Проверяет публичное имя и отсутствие скрытого поля результата.

        Returns:
            ``None``. Тест завершается успешно, если schema содержит только новый контракт.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_dir = root / "artifacts"
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root, artifacts_dir),
                tool_outputs_dir=artifacts_dir,
            )
            tool = build_python_tool(sandbox)

        self.assertEqual(tool.name, "python")
        self.assertIn("code", tool.args)
        self.assertIn("description", tool.args)
        self.assertNotIn("target_variable", tool.args)

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
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from pathlib import Path\n"
                            f"path = Path(r'{workspace_tool_path(workspace_file, root)}')\n"
                            "path.write_text('{\"ok\": true}', encoding='utf-8')\n"
                            "print(path.read_text(encoding='utf-8'))"
                        ),
                    }
                )
            )
            written_text = workspace_file.read_text(encoding="utf-8")

        self.assertTrue(payload["success"])
        self.assertEqual(written_text, '{"ok": true}')
        self.assertIn('{"ok": true}', payload["execution_output"])
        self.assertNotIn("target_variable", payload)
        self.assertNotIn("variable_preview", payload)

    def test_open_uses_configured_artifacts_dir(self) -> None:
        """Проверяет запись файла в каталог артефактов из настроек sandbox.

        Returns:
            ``None``; тест подтверждает использование ``ARTIFACTS_DIR``.
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
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from pathlib import Path\n"
                            "output_path = Path(ARTIFACTS_DIR) / 'my_notebook.ipynb'\n"
                            "with open(output_path, 'w', encoding='utf-8') as file:\n"
                            "    file.write('{}')\n"
                            "print(str(output_path))"
                        ),
                    }
                )
            )

            notebook_path = outputs_dir / "my_notebook.ipynb"
            self.assertTrue(payload["success"])
            self.assertTrue(notebook_path.exists())
        self.assertIn("configured_outputs", payload["execution_output"])

    def test_python_can_run_file_side_effect_without_print(self) -> None:
        """Проверяет выполнение кода без переменной результата для файлового side effect.

        Returns:
            ``None``; тест подтверждает выполнение side effect без stdout.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_dir = root / "artifacts"
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root, artifacts_dir),
                tool_outputs_dir=artifacts_dir,
            )
            tool = build_python_tool(sandbox)

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
        self.assertEqual(payload["execution_output"], "")
        self.assertEqual(payload["artifacts"], [])
        self.assertTrue(side_effect_exists)

    def test_plain_python_write_registers_artifact(self) -> None:
        """Проверяет сохранение JSON обычным Python-кодом и возврат artifact metadata.

        Returns:
            ``None``. Тест подтверждает, что helper регистрирует созданный файл.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_dir = root / "artifacts"
            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root, artifacts_dir),
                tool_outputs_dir=artifacts_dir,
            )
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from pathlib import Path\n"
                            "import json\n"
                            "path = Path(ARTIFACTS_DIR) / 'result.json'\n"
                            "path.write_text(json.dumps({'ok': True}), encoding='utf-8')\n"
                            "print(path)"
                        ),
                    }
                )
            )

            report_path = artifacts_dir / "result.json"
            report_exists = report_path.exists()

        self.assertTrue(payload["success"])
        self.assertTrue(report_exists)
        self.assertEqual(payload["artifacts"][0]["path"], "/artifacts/result.json")
        self.assertEqual(payload["artifacts"][0]["type"], "json")
        self.assertIn("result.json", payload["execution_output"])

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
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "from functions import rows_to_dataframe\n"
                            "print(rows_to_dataframe([{'value': 1}]).shape[0])"
                        ),
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("1", payload["execution_output"])

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
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "result = read_pickle_file("
                            f"r'{workspace_tool_path(pickle_path, root)}'"
                            ")\n"
                            "print(result)"
                        ),
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("'value': 7", payload["execution_output"])

    def test_resolve_workspace_path_maps_artifact_path_for_pandas(self) -> None:
        """Проверяет чтение pandas по workspace-пути через helper разрешения пути.

        Returns:
            ``None``; тест подтверждает, что pandas получает реальный путь ОС.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts_dir = root / "artifacts"
            artifacts_dir.mkdir()
            pickle_path = artifacts_dir / "data.pkl"
            with pickle_path.open("wb") as file:
                pickle.dump([{"value": 11}], file)

            sandbox = DeepAgentPythonSandbox(
                working_directory=root,
                readable_roots=(root,),
                tool_outputs_dir=artifacts_dir,
            )
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "df = pd.read_pickle("
                            "resolve_workspace_path(r'/artifacts/data.pkl')"
                            ")\n"
                            "print(df[0]['value'])"
                        ),
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("11", payload["execution_output"])

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
            tool = build_python_tool(sandbox)

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
            tool = build_python_tool(sandbox)

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
                            "print(completed.stdout.strip())"
                        ),
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("42", payload["execution_output"])

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
            tool = build_python_tool(sandbox)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": (
                            "import os\n"
                            "from pathlib import Path\n"
                            "os.remove('remove.txt')\n"
                            "Path('unlink.txt').unlink()\n"
                            "print('deleted')"
                        ),
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
            tool = build_python_tool(sandbox)
            long_comment = "#" + ("x" * 55_000)

            payload = json.loads(
                tool.invoke(
                    {
                        "code": f"{long_comment}\nprint(123)",
                    }
                )
            )

        self.assertTrue(payload["success"])
        self.assertIn("123", payload["execution_output"])


if __name__ == "__main__":
    unittest.main()
