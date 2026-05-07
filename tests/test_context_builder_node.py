from __future__ import annotations

import tempfile
import unittest
from asyncio import run
from pathlib import Path

from planner_agent.agent_nodes.context_builder_node import context_builder_node
from planner_agent.models import AgentState
from planner_agent.services.lineage_service import LineageService
from planner_agent.services.memory_service import MemoryService
from planner_agent.services.skills_service import SkillsService


class ContextBuilderNodeTests(unittest.TestCase):
    def test_context_builder_freezes_memory_and_builds_skills_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_dir = root / "memory"
            skills_dir = root / "skills"

            memory = MemoryService(memory_dir)
            (memory_dir / "user.md").write_text("Prefer compact answers.\n", encoding="utf-8")
            (memory_dir / "project.md").write_text("Use artifact IDs in reports.\n", encoding="utf-8")

            skill_dir = skills_dir / "insight-design"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: insight-design\n"
                "description: Build compact behavioral insights.\n"
                "---\n"
                "# Procedure\n\nSeparate facts from interpretation.\n",
                encoding="utf-8",
            )

            lineage = LineageService(root / "runs")
            run_record = lineage.create_run(initial_user_query="Analyze data")
            parent = lineage.create_state_node(
                run_id=run_record.run_id,
                node_type="context_snapshot",
                title="Context snapshot",
            )

            command = run(
                context_builder_node(
                    AgentState(
                        run_id=run_record.run_id,
                        current_node_id=parent.node_id,
                        parent_node_ids=[parent.node_id],
                    ),
                    memory_service=memory,
                    skills_service=SkillsService(skills_dir),
                    lineage_service=lineage,
                )
            )

            update = command.update
            self.assertEqual(command.goto, "planner")
            self.assertIn("Prefer compact answers.", update["memory_snapshot"])
            self.assertIn("Use artifact IDs in reports.", update["memory_snapshot"])
            self.assertIn("insight-design", update["skills_index"])
            self.assertEqual(len(update["lineage_events"]), 1)
            self.assertEqual(update["parent_node_ids"], [update["current_node_id"]])

            node = lineage.get_node(run_record.run_id, update["current_node_id"])
            self.assertIsNotNone(node)
            self.assertEqual(node.node_type, "research_context_built")
            self.assertEqual(node.parent_ids, [parent.node_id])

            snapshot = lineage.load_snapshot(run_record.run_id, node.node_id)
            self.assertIn("Prefer compact answers.", snapshot["memory_snapshot"])
            self.assertIn("insight-design", snapshot["skills_index"])


if __name__ == "__main__":
    unittest.main()
