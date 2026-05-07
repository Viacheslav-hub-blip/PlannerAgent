from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from planner_agent.schemas.lineage import BranchRequest, StateNode
from planner_agent.services.artifact_service import ArtifactService
from planner_agent.services.lineage_service import LineageService


class BranchArtifactTests(unittest.TestCase):
    def test_branch_from_node_registers_selected_edited_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            artifacts = ArtifactService(tmp)

            source_run = lineage.create_run(initial_user_query="Analyze source data")
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
            lineage.append_node(
                source_node,
                state={"artifact_index": {source_artifact.artifact_id: source_artifact.model_dump(mode="json")}},
            )

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

            branch_nodes = lineage.get_nodes(branch.run_id)
            self.assertEqual(len(branch_nodes), 1)
            self.assertEqual(branch_nodes[0].node_type, "branch_started")
            self.assertEqual(len(branch_nodes[0].artifact_refs), 1)

            branch_artifact = artifacts.list_artifacts(branch.run_id)[0]
            self.assertEqual(branch_artifact.kind, "dataset")
            self.assertEqual(branch_artifact.uri, str(edited_path.resolve()))
            self.assertNotEqual(branch_artifact.checksum, source_artifact.checksum)
            self.assertTrue(branch_artifact.metadata["branch_artifact"])
            self.assertTrue(branch_artifact.metadata["edited_override"])
            self.assertEqual(
                branch_artifact.metadata["branched_from_artifact_id"],
                source_artifact.artifact_id,
            )

            snapshot = lineage.load_snapshot(branch.run_id, branch_nodes[0].node_id)
            self.assertEqual(snapshot["source_run_id"], source_run.run_id)
            self.assertEqual(snapshot["restored_artifact_refs"], [branch_artifact.artifact_id])
            self.assertIn(branch_artifact.artifact_id, snapshot["artifact_index"])


if __name__ == "__main__":
    unittest.main()
