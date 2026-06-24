"""Тесты tool получения внутренней структуры агента.

Содержит:
- ProjectStructureToolTests: проверки текстового отчета структуры агента без содержимого skills.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deep_agent.settings import workspace_tool_path
from deep_agent.tools.project_structure import build_project_structure_report


class ProjectStructureToolTests(unittest.TestCase):
    """Проверяет построение структуры проекта для ``get_project_structure``."""

    def test_project_structure_report_returns_agent_files_without_skill_contents(self) -> None:
        """Проверяет, что отчет содержит внутренние файлы и только путь к skills.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            nested_dir = workspace / "deep_agent" / "runtime"
            skill_dir = workspace / "deep_agent" / "skills" / "demo"
            tests_dir = workspace / "tests"
            scripts_dir = workspace / "scripts"
            nested_dir.mkdir(parents=True)
            skill_dir.mkdir(parents=True)
            tests_dir.mkdir()
            scripts_dir.mkdir()
            (workspace / "AGENTS.md").write_text("# Memory\n", encoding="utf-8")
            (workspace / "README.md").write_text("# Readme\n", encoding="utf-8")
            (workspace / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (tests_dir / "test_sample.py").write_text("# test\n", encoding="utf-8")
            (scripts_dir / "script.py").write_text("# script\n", encoding="utf-8")
            runtime_file = nested_dir / "sample.py"
            skill_path = skill_dir / "SKILL.md"
            runtime_file.write_text("# runtime\n", encoding="utf-8")
            skill_path.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n# Demo\n",
                encoding="utf-8",
            )

            report = build_project_structure_report(
                workspace_root=workspace,
                max_tree_entries=50,
            )

        self.assertIn("# Agent Structure", report)
        self.assertIn(workspace_tool_path(workspace, workspace, directory=True), report)
        self.assertIn(
            workspace_tool_path(workspace / "deep_agent" / "skills", workspace, directory=True),
            report,
        )
        self.assertIn("sample.py", report)
        self.assertNotIn("## Skills", report)
        self.assertNotIn(workspace_tool_path(skill_path, workspace), report)
        self.assertNotIn("Demo skill", report)
        self.assertNotIn("AGENTS.md", report)
        self.assertNotIn("README.md", report)
        self.assertNotIn("pyproject.toml", report)
        self.assertNotIn("test_sample.py", report)
        self.assertNotIn("script.py", report)

    def test_project_structure_report_uses_configured_agent_root(self) -> None:
        """Проверяет, что отчет использует фактический путь агента из конфигурации.

        Returns:
            ``None``.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            agent_root = workspace / "deepagent_langchain" / "deep_agent"
            skills_root = agent_root / "skills"
            agent_root.mkdir(parents=True)
            skills_root.mkdir(parents=True)
            (agent_root / "agent.py").write_text("# agent\n", encoding="utf-8")

            report = build_project_structure_report(
                workspace_root=workspace,
                agent_root=agent_root,
                skills_root=skills_root,
                max_tree_entries=50,
            )

        self.assertIn(
            workspace_tool_path(agent_root, workspace, directory=True),
            report,
        )
        self.assertIn(
            workspace_tool_path(skills_root, workspace, directory=True),
            report,
        )
        self.assertIn("agent.py", report)
        self.assertNotIn("- Agent internals: `/deep_agent/`", report)


if __name__ == "__main__":
    unittest.main()
