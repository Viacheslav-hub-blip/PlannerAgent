"""Unit-тесты execute_python_code для DeepAgent."""

from __future__ import annotations

import json
import pickle
import tempfile
import unittest
from pathlib import Path

from deep_agent_test.execute_python_code_tool import build_execute_python_code_tool
from deep_agent_test.python_sandbox import DeepAgentPythonSandbox
from deep_agent_test.settings import PROJECT_ROOT


class ExecutePythonCodeToolTests(unittest.TestCase):
    def _build_tool(self, temp_dir: Path):
        sandbox = DeepAgentPythonSandbox(
            working_directory=PROJECT_ROOT,
            readable_roots=(PROJECT_ROOT, temp_dir),
            tool_outputs_dir=temp_dir,
        )
        return build_execute_python_code_tool(sandbox), sandbox

    def test_successful_execution_returns_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tool, _sandbox = self._build_tool(Path(temp_dir))
            payload = json.loads(
                tool.invoke(
                    {
                        "code": "result = 2 + 2\nprint(result)",
                        "target_variable": "result",
                        "description": "simple sum",
                    }
                )
            )
            self.assertTrue(payload["success"])
            self.assertIn("result", payload["available_variables"])
            self.assertIn("sandbox_helpers", payload)

    def test_pickle_helper_reads_rows(self) -> None:
        rows = [{"id": 1, "city": "Moscow"}, {"id": 2, "city": "SPB"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            pkl_path = Path(temp_dir) / "rows.pkl"
            with pkl_path.open("wb") as file:
                pickle.dump(rows, file)

            tool, _sandbox = self._build_tool(Path(temp_dir))
            code = (
                f"rows = read_pickle_file(r'{pkl_path}')\n"
                "print(len(rows))\n"
                "result = rows"
            )
            payload = json.loads(tool.invoke({"code": code, "target_variable": "result"}))
            self.assertTrue(payload["success"])
            self.assertIn("execution_output", payload)

    def test_execution_error_returns_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tool, _sandbox = self._build_tool(Path(temp_dir))
            payload = json.loads(
                tool.invoke({"code": "raise ValueError('broken step')", "description": "fail"})
            )
            self.assertFalse(payload["success"])
            self.assertIn("traceback", payload)
            self.assertTrue(payload["traceback"])
            self.assertIn("possible_causes", payload)
            self.assertIn("solution_options", payload)
            self.assertIn("retry_guidance", payload)

    def test_validation_error_returns_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tool, _sandbox = self._build_tool(Path(temp_dir))
            payload = json.loads(tool.invoke({"code": "import forbidden_module"}))
            self.assertFalse(payload["success"])
            self.assertIn("traceback", payload)
            self.assertIn("forbidden_module", payload["error"])


if __name__ == "__main__":
    unittest.main()
