from __future__ import annotations

import tempfile
import unittest
from asyncio import run

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from planner_agent.agent_nodes.validator_node import validator_node
from planner_agent.models import Task, TaskStatus, ValidatorPayload
from planner_agent.services.lineage_service import LineageService


class ValidatorLineageTests(unittest.TestCase):
    def test_validator_creates_validation_completed_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            run_record = lineage.create_run(initial_user_query="Analyze case")
            task_node = lineage.create_state_node(
                run_id=run_record.run_id,
                node_type="task_completed",
                title="Task completed",
            )
            task = Task(
                task_id="1",
                description="Inspect data",
                result_preview="Data was inspected.",
                full_result="Data was inspected successfully.",
                status=TaskStatus.NEEDS_VALIDATION,
            )
            llm = FakeListChatModel(
                responses=[
                    '{"is_valid":true,"confidence":0.91,"reasoning":"Result matches the task."}'
                ]
            )

            command = run(
                validator_node(
                    ValidatorPayload(
                        task=task,
                        run_id=run_record.run_id,
                        parent_node_ids=[task_node.node_id],
                    ),
                    llm=llm,
                    prompt="Return JSON validation.",
                    lineage_service=lineage,
                )
            )

            update = command.update
            self.assertEqual(command.goto, "replanner")
            self.assertEqual(update["plan"]["1"].status, TaskStatus.COMPLETED)
            self.assertEqual(len(update["lineage_events"]), 1)
            self.assertTrue(update["validation_results"]["1"]["validation_passed"])

            nodes = lineage.get_nodes(run_record.run_id)
            self.assertEqual(nodes[-1].node_type, "validation_completed")
            self.assertEqual(nodes[-1].parent_ids, [task_node.node_id])
            self.assertEqual(nodes[-1].metadata["validation_score"], 0.91)

            snapshot = lineage.load_snapshot(run_record.run_id, nodes[-1].node_id)
            self.assertTrue(snapshot["validation"]["passed"])
            self.assertEqual(snapshot["task"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
