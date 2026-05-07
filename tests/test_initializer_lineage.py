from __future__ import annotations

import tempfile
import unittest
from asyncio import run

import pandas as pd
from langchain_core.messages import HumanMessage

from planner_agent.agent_nodes.initialize_node import initializer_node
from planner_agent.models import AgentState
from planner_agent.services.lineage_service import LineageService


class FakeSandbox:
    globals = {}

    async def get_all_variable_previews(self) -> dict[str, str]:
        return {"df_current": "shape=(1, 3)"}


class DataFrameSandbox:
    def __init__(self) -> None:
        self.globals = {
            "df_current": pd.DataFrame(
                {
                    "amount": [100.0, None, 300.0],
                    "merchant": ["Metro", "", None],
                }
            )
        }

    async def get_all_variable_previews(self) -> dict[str, str]:
        return {"df_current": "shape=(3, 2)"}


class InitializerLineageTests(unittest.TestCase):
    def test_initializer_creates_run_started_and_context_snapshot_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            command = run(
                initializer_node(
                    AgentState(
                        session_id="session-1",
                        user_id="user-1",
                        messages=[HumanMessage(content="Analyze this case")],
                    ),
                    sandbox=FakeSandbox(),
                    filesystem_context={"workspace_root": tmp, "contexts_dir": tmp},
                    lineage_service=lineage,
                )
            )

            update = command.update
            self.assertEqual(command.goto, "context_builder")
            self.assertTrue(update["run_id"])
            self.assertTrue(update["current_node_id"])
            self.assertEqual(update["initial_user_query"], "Analyze this case")
            self.assertEqual(len(update["lineage_events"]), 2)

            run_record = lineage.get_run(update["run_id"])
            self.assertIsNotNone(run_record)

            nodes = lineage.get_nodes(update["run_id"])
            self.assertEqual(len(nodes), 2)
            self.assertEqual(nodes[0].node_type, "run_started")
            self.assertEqual(nodes[1].node_type, "context_snapshot")
            self.assertEqual(run_record.root_node_id, nodes[0].node_id)
            self.assertEqual(update["current_node_id"], nodes[1].node_id)
            self.assertEqual(nodes[1].parent_ids, [nodes[0].node_id])

            snapshot = lineage.load_snapshot(update["run_id"], update["current_node_id"])
            self.assertEqual(snapshot["run_id"], update["run_id"])
            self.assertEqual(snapshot["data_schemas"], {"df_current": "shape=(1, 3)"})

    def test_initializer_continues_existing_branch_run_without_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lineage = LineageService(tmp)
            branch_run = lineage.create_run(
                initial_user_query="Continue from branch",
                session_id="session-branch",
                user_id="user-branch",
                parent_run_id="source-run",
                source_node_id="source-node",
            )
            branch_node = lineage.create_state_node(
                run_id=branch_run.run_id,
                node_type="branch_started",
                title="Branch started",
                created_by="user",
                state={"run_id": branch_run.run_id},
            )

            command = run(
                initializer_node(
                    AgentState(
                        run_id=branch_run.run_id,
                        session_id="session-branch",
                        user_id="user-branch",
                        current_node_id=branch_node.node_id,
                        parent_node_ids=[branch_node.node_id],
                        messages=[HumanMessage(content="Continue from branch")],
                    ),
                    sandbox=FakeSandbox(),
                    filesystem_context={"workspace_root": tmp, "contexts_dir": tmp},
                    lineage_service=lineage,
                )
            )

            update = command.update
            self.assertEqual(update["run_id"], branch_run.run_id)
            self.assertEqual(len(update["lineage_events"]), 1)

            nodes = lineage.get_nodes(branch_run.run_id)
            self.assertEqual(len(nodes), 2)
            self.assertEqual(nodes[0].node_type, "branch_started")
            self.assertEqual(nodes[1].node_type, "context_snapshot")
            self.assertEqual(nodes[1].parent_ids, [branch_node.node_id])
            self.assertTrue(nodes[1].metadata["resumed_existing_run"])

            runs = lineage.list_runs()
            self.assertEqual(len(runs), 1)

    def test_initializer_enriches_dataframe_schema_with_empty_cell_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command = run(
                initializer_node(
                    AgentState(messages=[HumanMessage(content="Analyze this case")]),
                    sandbox=DataFrameSandbox(),
                    filesystem_context={"workspace_root": tmp, "contexts_dir": tmp},
                )
            )

            schema = command.update["data_schemas"]["df_current"]
            self.assertIn("shape=(3, 2)", schema)
            self.assertIn("empty_cells=3", schema)
            self.assertIn("columns_with_empty=2", schema)
            self.assertIn("amount=1", schema)
            self.assertIn("merchant=2", schema)


if __name__ == "__main__":
    unittest.main()
