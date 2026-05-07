from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import HumanMessage

from planner_agent.models import AgentState, Task, TaskStatus
from planner_agent.schemas.lineage import BranchRequest, StateNode
from planner_agent.services.artifact_service import ArtifactService
from planner_agent.services.branch_resume_service import BranchResumeService
from planner_agent.services.lineage_service import LineageService


class BranchResumeServiceTests(unittest.TestCase):
    def test_build_initial_state_restores_research_state_and_branch_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            artifacts = ArtifactService(tmp)

            source_run = lineage.create_run(
                initial_user_query="Analyze source data",
                session_id="session-1",
                user_id="user-1",
            )
            source_node = StateNode(
                run_id=source_run.run_id,
                node_type="task_completed",
                title="Task completed",
            )
            source_artifact = artifacts.write_artifact(
                run_id=source_run.run_id,
                node_id=source_node.node_id,
                kind="dataset",
                filename="exports/transactions.csv",
                content="event_id,amount\n1,100\n",
                mime_type="text/csv",
                summary="Original transaction export",
                metadata={"editable": True, "reusable": True},
            )
            source_node.artifact_refs = [source_artifact.artifact_id]

            source_state = AgentState(
                run_id=source_run.run_id,
                session_id="session-1",
                user_id="user-1",
                current_node_id=source_node.node_id,
                parent_node_ids=[source_node.node_id],
                initial_user_query=source_run.initial_user_query,
                messages=[HumanMessage(content="Old chat message")],
                plan={
                    "1": Task(
                        task_id="1",
                        description="Load transactions",
                        status=TaskStatus.COMPLETED,
                        artifact_refs=[source_artifact.artifact_id],
                    )
                },
                memory_snapshot="Use compact evidence tables.",
                data_schemas={"df_current": "shape=(10, 5)"},
                filesystem_context={"workspace_root": tmp},
                artifact_index={
                    source_artifact.artifact_id: source_artifact.model_dump(mode="json")
                },
                evidence_map={"1": {"artifact_refs": [source_artifact.artifact_id]}},
            )
            lineage.append_node(source_node, state=source_state)

            edited_path = Path(tmp) / "edited_transactions.csv"
            edited_path.write_text("event_id,amount\n1,200\n", encoding="utf-8")

            branch = lineage.branch_from(
                BranchRequest(
                    source_run_id=source_run.run_id,
                    source_node_id=source_node.node_id,
                    new_task="Continue with edited export",
                    branch_mode="revise",
                    artifact_refs=[source_artifact.artifact_id],
                    artifact_overrides={
                        source_artifact.artifact_id: str(edited_path),
                    },
                )
            )
            branch_node = lineage.get_nodes(branch.run_id)[0]
            branch_artifact = artifacts.list_artifacts(branch.run_id)[0]

            state = BranchResumeService(lineage).build_initial_state(
                branch_run_id=branch.run_id,
            )

            self.assertEqual(state.run_id, branch.run_id)
            self.assertEqual(state.session_id, "session-1")
            self.assertEqual(state.user_id, "user-1")
            self.assertEqual(state.current_node_id, branch_node.node_id)
            self.assertEqual(state.parent_node_ids, [branch_node.node_id])
            self.assertEqual(state.initial_user_query, "Continue with edited export")
            self.assertEqual(len(state.messages), 1)
            self.assertEqual(state.messages[0].content, "Continue with edited export")
            self.assertEqual(state.plan["1"].status, TaskStatus.COMPLETED)
            self.assertEqual(state.memory_snapshot, "Use compact evidence tables.")
            self.assertEqual(state.data_schemas, {"df_current": "shape=(10, 5)"})
            self.assertEqual(state.filesystem_context, {"workspace_root": tmp})
            self.assertIn(branch_artifact.artifact_id, state.artifact_index)
            self.assertNotIn(source_artifact.artifact_id, state.artifact_index)
            self.assertIn("branch_context", state.ephemeral_recalls)
            self.assertIn(branch_artifact.artifact_id, state.ephemeral_recalls["branch_context"])

    def test_build_initial_state_can_skip_completed_research_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            source_run = lineage.create_run(initial_user_query="Analyze")
            source_node = lineage.create_state_node(
                run_id=source_run.run_id,
                node_type="task_completed",
                title="Task completed",
                state=AgentState(
                    run_id=source_run.run_id,
                    plan={
                        "1": Task(
                            task_id="1",
                            description="Completed task",
                            status=TaskStatus.COMPLETED,
                        )
                    },
                    memory_snapshot="Durable memory",
                    evidence_map={"1": {"ok": True}},
                ),
            )

            branch = lineage.branch_from(
                BranchRequest(
                    source_run_id=source_run.run_id,
                    source_node_id=source_node.node_id,
                    new_task="Start alternative",
                    branch_mode="alternative",
                    include_completed_tasks=False,
                    include_memory_snapshot=False,
                )
            )

            state = BranchResumeService(lineage).build_initial_state(
                branch_run_id=branch.run_id,
            )

            self.assertEqual(state.plan, {})
            self.assertEqual(state.evidence_map, {})
            self.assertEqual(state.memory_snapshot, "")
            self.assertEqual(state.initial_user_query, "Start alternative")


if __name__ == "__main__":
    unittest.main()
