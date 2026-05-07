from __future__ import annotations

import tempfile
import unittest
from asyncio import run
from pathlib import Path

from langchain_core.tools import tool

from planner_agent.models import Task
from planner_agent.services.artifact_service import ArtifactService
from planner_agent.tools.artifact_wrappers import wrap_tools_for_artifacts


class ToolArtifactTests(unittest.TestCase):
    def test_tool_result_is_saved_as_reusable_artifact(self) -> None:
        @tool("download_transactions")
        async def download_transactions(depth_days: int, amount: float) -> str:
            """Download transactions from an approved internal source."""
            return f"transactions depth={depth_days} amount={amount}"

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactService(tmp)
            task = Task(task_id="case/1", description="Load source data")
            artifact_index: dict = {}
            tool_traces: list[dict] = []

            wrapped_tool = wrap_tools_for_artifacts(
                tools=[download_transactions],
                artifact_service=artifacts,
                run_id="run-1",
                node_id="node-1",
                task=task,
                artifact_index=artifact_index,
                tool_traces=tool_traces,
            )[0]

            result = run(
                wrapped_tool.ainvoke(
                    {"depth_days": 30, "amount": 1000.0}
                )
            )

            self.assertEqual(result, "transactions depth=30 amount=1000.0")
            self.assertEqual(len(task.artifact_refs), 1)
            self.assertEqual(set(artifact_index), set(task.artifact_refs))
            self.assertEqual(len(tool_traces), 1)

            stored = artifacts.list_artifacts("run-1")
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].kind, "tool_trace")
            self.assertEqual(stored[0].node_id, "node-1")
            self.assertEqual(stored[0].metadata["tool_name"], "download_transactions")
            self.assertTrue(stored[0].metadata["reusable"])

            content = Path(stored[0].uri).read_text(encoding="utf-8")
            self.assertIn("Tool: download_transactions", content)
            self.assertIn('"depth_days": 30', content)
            self.assertIn("transactions depth=30 amount=1000.0", content)

    def test_large_text_result_is_captured_and_replaced_with_reference(self) -> None:
        @tool("export_long_notes")
        async def export_long_notes(client_id: str) -> str:
            """Return a large text export."""
            return f"client={client_id}\n" + ("event\n" * 12_000)

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactService(tmp)
            task = Task(task_id="large-text", description="Load long notes")
            artifact_index: dict = {}
            tool_traces: list[dict] = []

            wrapped_tool = wrap_tools_for_artifacts(
                tools=[export_long_notes],
                artifact_service=artifacts,
                run_id="run-large-text",
                node_id="node-large-text",
                task=task,
                artifact_index=artifact_index,
                tool_traces=tool_traces,
            )[0]

            result = run(wrapped_tool.ainvoke({"client_id": "client-1"}))

            self.assertIsInstance(result, str)
            self.assertIn("Tool result was saved as an artifact", result)
            self.assertIn("artifact_id:", result)
            self.assertIn("uri:", result)
            self.assertIn("data_scope: partial_preview", result)
            self.assertIn("full_result_available_in_artifact: true", result)
            self.assertIn("preview_is_truncated: true", result)
            self.assertIn("worker_disclosure_required: true", result)
            self.assertIn("The preview below is not the full tool result", result)

            stored = artifacts.list_artifacts("run-large-text")
            self.assertEqual(len(stored), 2)
            captured_artifact = next(
                artifact
                for artifact in stored
                if artifact.metadata.get("artifact_role") == "captured_tool_result"
            )
            trace_artifact = next(
                artifact
                for artifact in stored
                if artifact.metadata.get("artifact_role") == "tool_call_trace"
            )
            self.assertEqual(captured_artifact.kind, "source_excerpt")
            self.assertTrue(captured_artifact.metadata["reusable"])
            self.assertTrue(captured_artifact.metadata["editable"])
            self.assertTrue(trace_artifact.metadata["captured"])
            self.assertEqual(
                trace_artifact.metadata["captured_artifact_refs"],
                [captured_artifact.artifact_id],
            )
            trace_content = Path(trace_artifact.uri).read_text(encoding="utf-8")
            self.assertIn("Captured: True", trace_content)
            self.assertLess(len(trace_content), 10_000)
            self.assertEqual(set(task.artifact_refs), set(artifact_index))

    def test_large_list_result_is_captured_as_dataset_without_tool_contract(self) -> None:
        @tool("load_events")
        async def load_events(client_id: str) -> list[dict]:
            """Return many events as a normal Python list."""
            return [
                {
                    "client_id": client_id,
                    "event_id": index,
                    "amount": index * 10,
                    "description": "regular payment event",
                }
                for index in range(2_000)
            ]

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactService(tmp)
            task = Task(task_id="large-list", description="Load events")
            artifact_index: dict = {}
            tool_traces: list[dict] = []

            wrapped_tool = wrap_tools_for_artifacts(
                tools=[load_events],
                artifact_service=artifacts,
                run_id="run-large-list",
                node_id="node-large-list",
                task=task,
                artifact_index=artifact_index,
                tool_traces=tool_traces,
            )[0]

            result = run(wrapped_tool.ainvoke({"client_id": "client-2"}))

            self.assertIsInstance(result, str)
            self.assertIn("artifact_id:", result)
            self.assertIn("original_size_estimate_chars:", result)
            self.assertIn("data_scope: partial_preview", result)
            self.assertIn("worker_disclosure_required: true", result)

            stored = artifacts.list_artifacts("run-large-list")
            captured_artifact = next(
                artifact
                for artifact in stored
                if artifact.metadata.get("artifact_role") == "captured_tool_result"
            )
            self.assertEqual(captured_artifact.kind, "dataset")
            self.assertEqual(captured_artifact.mime_type, "application/json")
            captured_content = Path(captured_artifact.uri).read_text(encoding="utf-8")
            self.assertIn('"event_id": 1999', captured_content)

    def test_small_structured_result_is_returned_inline_and_saved_as_artifact(self) -> None:
        """Проверяет, что маленький list/dict остается inline, но сохраняется для responder."""

        @tool("load_day_events")
        async def load_day_events(client_id: str) -> list[dict]:
            """Return a small structured events export."""
            return [
                {"client_id": client_id, "event_id": "evt-1", "amount": 100},
                {"client_id": client_id, "event_id": "evt-2", "amount": 200},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = ArtifactService(tmp)
            task = Task(task_id="small-list", description="Load day events")
            artifact_index: dict = {}
            tool_traces: list[dict] = []

            wrapped_tool = wrap_tools_for_artifacts(
                tools=[load_day_events],
                artifact_service=artifacts,
                run_id="run-small-list",
                node_id="node-small-list",
                task=task,
                artifact_index=artifact_index,
                tool_traces=tool_traces,
            )[0]

            result = run(wrapped_tool.ainvoke({"client_id": "client-2"}))

            self.assertIsInstance(result, list)
            self.assertEqual(result[0]["event_id"], "evt-1")

            stored = artifacts.list_artifacts("run-small-list")
            dataset_artifact = next(
                artifact
                for artifact in stored
                if artifact.metadata.get("artifact_role") == "captured_tool_result"
            )
            self.assertEqual(dataset_artifact.kind, "dataset")
            self.assertEqual(
                dataset_artifact.metadata["capture_reason"],
                "inline_structured_result",
            )
            self.assertIn(dataset_artifact.artifact_id, task.artifact_refs)
            self.assertIn(dataset_artifact.artifact_id, artifact_index)

    def test_direct_file_path_result_is_registered_as_editable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "transactions.csv"
            export_path.write_text("event_id,amount\n1,100\n", encoding="utf-8")

            @tool("export_transactions")
            async def export_transactions(client_id: str) -> str:
                """Export transactions to a reusable file and return its path."""
                return str(export_path)

            artifacts = ArtifactService(tmp)
            task = Task(task_id="2", description="Export transactions")
            artifact_index: dict = {}
            tool_traces: list[dict] = []

            wrapped_tool = wrap_tools_for_artifacts(
                tools=[export_transactions],
                artifact_service=artifacts,
                run_id="run-2",
                node_id="node-2",
                task=task,
                artifact_index=artifact_index,
                tool_traces=tool_traces,
            )[0]

            result = run(wrapped_tool.ainvoke({"client_id": "client-1"}))

            stored = artifacts.list_artifacts("run-2")
            self.assertIn("artifact_id:", result)
            self.assertEqual([artifact.kind for artifact in stored], ["dataset", "tool_trace"])
            self.assertEqual(stored[0].uri, str(export_path.resolve()))
            self.assertTrue(stored[0].metadata["reusable"])
            self.assertTrue(stored[0].metadata["editable"])
            self.assertEqual(set(task.artifact_refs), set(artifact_index))


if __name__ == "__main__":
    unittest.main()
