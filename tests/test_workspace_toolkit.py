from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from asyncio import run

from planner_agent.toolkits.workspace_toolkit import (
    DEFAULT_WORKSPACE_TOOL_NAMES,
    build_workspace_tools,
)


class FakeSandbox:
    last_dataframe_variable = None
    globals = {}

    async def get_all_variable_previews(self) -> dict[str, str]:
        return {}

    async def add_variable(self, name: str, value: object) -> None:
        self.globals[name] = value

    async def get_variable(self, name: str) -> object:
        return self.globals.get(name)


class WorkspaceToolkitTests(unittest.TestCase):
    def test_default_workspace_surface_is_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = build_workspace_tools(FakeSandbox(), workspace_root=tmp)
            tool_names = {tool.name for tool in tools}

        self.assertEqual(tool_names, set(DEFAULT_WORKSPACE_TOOL_NAMES))
        self.assertNotIn("get_list_files_from_root_directory", tool_names)
        self.assertNotIn("replace_current_dataframe", tool_names)

    def test_workspace_read_write_file_tools_are_safe_and_chunked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = {
                tool.name: tool
                for tool in build_workspace_tools(FakeSandbox(), workspace_root=tmp)
            }

            write_result = run(
                tools["workspace_write_file"].ainvoke(
                    {"file_path": "notes/case.md", "content": "abcdef", "overwrite": False}
                )
            )
            read_result = run(
                tools["workspace_read_file"].ainvoke(
                    {"file_path": "notes/case.md", "offset": 2, "max_chars": 3}
                )
            )
            denied_result = run(
                tools["workspace_write_file"].ainvoke(
                    {"file_path": "scripts/run.ps1", "content": "echo no", "overwrite": True}
                )
            )

        self.assertIn("File written", write_result)
        self.assertIn("Content:\ncde", read_result)
        self.assertIn("not allowed", denied_result)


if __name__ == "__main__":
    unittest.main()
