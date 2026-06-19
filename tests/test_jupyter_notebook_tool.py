"""Тесты инструмента конвертации Jupyter Notebook.

Содержит:
- JupyterNotebookToolTests: проверки конвертации `.py` percent-script и `.ipynb`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deep_agent.settings import workspace_tool_path
from deep_agent.tools.jupyter_notebook import (
    CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME,
    build_convert_jupyter_notebook_tool,
    convert_jupyter_notebook_file,
)


class JupyterNotebookToolTests(unittest.TestCase):
    """Проверяет конвертацию Jupyter Notebook без выполнения кода."""

    def test_py_to_ipynb_creates_notebook_from_percent_script(self) -> None:
        """Проверяет создание `.ipynb` из `.py` файла с percent-ячейками.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            source_file = workspace / "analysis.py"
            output_file = workspace / "analysis.ipynb"
            source_file.write_text(
                "# %% [markdown]\n"
                "# # Заголовок\n"
                "#\n"
                "# Описание\n"
                "# %%\n"
                "value = 2 + 2\n"
                "print(value)\n",
                encoding="utf-8",
            )

            result = convert_jupyter_notebook_file(
                mode="py_to_ipynb",
                source_path=workspace_tool_path(source_file, workspace),
                output_path="analysis.ipynb",
                workspace_root=workspace,
            )

            payload = json.loads(result)
            notebook = json.loads(output_file.read_text(encoding="utf-8"))

        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "py_to_ipynb")
        self.assertEqual(payload["cells_count"], 2)
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "python3")
        self.assertEqual(notebook["cells"][0]["cell_type"], "markdown")
        self.assertEqual(notebook["cells"][0]["source"], ["# Заголовок\n", "\n", "Описание\n"])
        self.assertEqual(notebook["cells"][1]["cell_type"], "code")
        self.assertEqual(notebook["cells"][1]["outputs"], [])
        self.assertIn("value = 2 + 2\n", notebook["cells"][1]["source"])

    def test_ipynb_to_py_creates_percent_script_without_outputs(self) -> None:
        """Проверяет создание `.py` percent-script из `.ipynb` без outputs.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            source_file = workspace / "analysis.ipynb"
            output_file = workspace / "analysis.py"
            source_file.write_text(
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "markdown",
                                "metadata": {},
                                "source": ["# Заголовок\n", "Описание\n"],
                            },
                            {
                                "cell_type": "code",
                                "execution_count": 3,
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

            result = convert_jupyter_notebook_file(
                mode="ipynb_to_py",
                source_path="analysis.ipynb",
                output_path=workspace_tool_path(output_file, workspace),
                workspace_root=workspace,
            )
            payload = json.loads(result)
            script_text = output_file.read_text(encoding="utf-8")

        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "ipynb_to_py")
        self.assertEqual(payload["cells_count"], 2)
        self.assertIn("# %% [markdown]\n", script_text)
        self.assertIn("# # Заголовок\n", script_text)
        self.assertIn("# %%\n", script_text)
        self.assertIn("value = 2 + 2\n", script_text)
        self.assertNotIn("outputs", script_text)
        self.assertNotIn("execution_count", script_text)

    def test_tool_wrapper_exposes_expected_name_and_invokes_conversion(self) -> None:
        """Проверяет имя tool и вызов через LangChain-интерфейс.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            source_file = workspace / "notebook.py"
            output_file = workspace / "notebook.ipynb"
            source_file.write_text("# %%\nprint('ok')\n", encoding="utf-8")
            tool = build_convert_jupyter_notebook_tool(workspace_root=workspace)

            result = tool.invoke(
                {
                    "mode": "py_to_ipynb",
                    "source_path": "notebook.py",
                    "output_path": "notebook.ipynb",
                }
            )
            output_exists = output_file.exists()

        payload = json.loads(result)
        self.assertEqual(tool.name, CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME)
        self.assertTrue(payload["success"])
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
