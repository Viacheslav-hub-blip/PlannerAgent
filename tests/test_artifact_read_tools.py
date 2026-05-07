"""Тесты LangChain tools для чтения и анализа artifacts.

Содержит:
- ArtifactReadToolsTests: проверки artifact_list, artifact_preview, artifact_read_chunk и
  аналитических tools для табличных artifacts.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.tools import tool

from planner_agent.agent_nodes.worker_node import _with_artifact_read_tools
from planner_agent.services.artifact_service import ArtifactService
from planner_agent.tools.artifact_read_tools import build_artifact_read_tools


@tool("custom_tool")
def custom_tool(value: str) -> str:
    """Return input value."""
    return value


class ArtifactReadToolsTests(unittest.TestCase):
    """Проверяет чтение artifacts через обычные LangChain tools."""

    def test_artifact_list_preview_and_read_chunk(self) -> None:
        """Проверяет список artifacts, preview и чтение bounded chunk."""

        with tempfile.TemporaryDirectory() as tmp:
            artifact_service = ArtifactService(tmp)
            artifact = artifact_service.write_artifact(
                run_id="run-1",
                node_id="node-1",
                kind="dataset",
                filename="events.json",
                content=json.dumps(
                    [{"event_id": index, "amount": index * 10} for index in range(20)],
                    ensure_ascii=False,
                ),
                mime_type="application/json",
                summary="Client events",
                metadata={
                    "reusable": True,
                    "editable": True,
                    "tool_name": "load_events",
                    "artifact_role": "captured_tool_result",
                },
            )
            tools = {
                tool.name: tool
                for tool in build_artifact_read_tools(
                    artifact_service=artifact_service,
                    run_id="run-1",
                )
            }

            list_payload = json.loads(
                tools["artifact_list"].invoke(
                    {
                        "kind": "dataset",
                        "reusable_only": True,
                        "editable_only": False,
                        "limit": 10,
                    }
                )
            )
            self.assertEqual(list_payload["total_matches"], 1)
            self.assertEqual(
                list_payload["artifacts"][0]["artifact_id"],
                artifact.artifact_id,
            )
            self.assertEqual(
                list_payload["artifacts"][0]["metadata"]["tool_name"],
                "load_events",
            )

            preview_payload = json.loads(
                tools["artifact_preview"].invoke(
                    {"artifact_id": artifact.artifact_id, "max_chars": 80}
                )
            )
            self.assertEqual(
                preview_payload["artifact"]["artifact_id"],
                artifact.artifact_id,
            )
            self.assertIn("event_id", preview_payload["preview"])
            self.assertLessEqual(preview_payload["preview_chars"], 80)
            self.assertEqual(preview_payload["data_scope"], "partial")
            self.assertTrue(preview_payload["truncated"])
            self.assertTrue(preview_payload["worker_disclosure_required"])
            self.assertGreater(preview_payload["total_chars"], preview_payload["preview_chars"])

            chunk_payload = json.loads(
                tools["artifact_read_chunk"].invoke(
                    {
                        "artifact_id": artifact.artifact_id,
                        "offset": 10,
                        "limit": 50,
                    }
                )
            )
            self.assertEqual(chunk_payload["offset"], 10)
            self.assertLessEqual(chunk_payload["content_chars"], 50)
            self.assertTrue(chunk_payload["has_more"])
            self.assertEqual(chunk_payload["data_scope"], "partial")
            self.assertTrue(chunk_payload["worker_disclosure_required"])
            self.assertEqual(
                chunk_payload["next_offset"],
                chunk_payload["offset"] + chunk_payload["content_chars"],
            )

    def test_artifact_read_chunk_rejects_binary_artifact(self) -> None:
        """Проверяет, что binary artifact не читается как текст."""

        with tempfile.TemporaryDirectory() as tmp:
            artifact_service = ArtifactService(tmp)
            artifact = artifact_service.write_artifact(
                run_id="run-2",
                node_id="node-2",
                kind="dataset",
                filename="payload.bin",
                content=b"\x00\x01\x02",
                mime_type="application/octet-stream",
                summary="Binary payload",
                metadata={"reusable": True},
            )
            tools = {
                tool.name: tool
                for tool in build_artifact_read_tools(
                    artifact_service=artifact_service,
                    run_id="run-2",
                )
            }

            chunk_payload = json.loads(
                tools["artifact_read_chunk"].invoke(
                    {"artifact_id": artifact.artifact_id}
                )
            )

            self.assertEqual(chunk_payload["error"], "artifact_is_not_text")
            self.assertEqual(chunk_payload["data_scope"], "unavailable")
            self.assertTrue(chunk_payload["worker_disclosure_required"])
            self.assertEqual(chunk_payload["content"], "")

    def test_worker_runtime_adds_artifact_read_tools_without_overriding_existing_names(self) -> None:
        """Проверяет runtime-добавление artifact tools в worker."""

        with tempfile.TemporaryDirectory() as tmp:
            artifact_service = ArtifactService(tmp)

            tools = _with_artifact_read_tools(
                tools=[custom_tool],
                artifact_service=artifact_service,
                run_id="run-3",
            )
            names = {item.name for item in tools}

            self.assertIn("custom_tool", names)
            self.assertIn("artifact_list", names)
            self.assertIn("artifact_preview", names)
            self.assertIn("artifact_read_chunk", names)
            self.assertIn("artifact_profile", names)
            self.assertIn("artifact_sample", names)
            self.assertIn("artifact_search", names)
            self.assertIn("artifact_value_counts", names)

            unchanged = _with_artifact_read_tools(
                tools=tools,
                artifact_service=artifact_service,
                run_id="run-3",
            )
            self.assertEqual(len(unchanged), len(tools))

    def test_artifact_analysis_tools_profile_sample_search_and_counts(self) -> None:
        """Проверяет универсальный анализ JSON artifact без доменных правил."""

        with tempfile.TemporaryDirectory() as tmp:
            artifact_service = ArtifactService(tmp)
            artifact = artifact_service.write_artifact(
                run_id="run-4",
                node_id="node-4",
                kind="dataset",
                filename="transactions.json",
                content=json.dumps(
                    [
                        {
                            "event_id": "evt-1",
                            "event_type": "payment",
                            "merchant": "Coffee",
                            "amount": 100,
                        },
                        {
                            "event_id": "evt-2",
                            "event_type": "payment",
                            "merchant": "Coffee",
                            "amount": 150,
                        },
                        {
                            "event_id": "evt-3",
                            "event_type": "login",
                            "merchant": "",
                            "amount": None,
                        },
                    ],
                    ensure_ascii=False,
                ),
                mime_type="application/json",
                summary="Transactions",
                metadata={"reusable": True},
            )
            tools = {
                tool.name: tool
                for tool in build_artifact_read_tools(
                    artifact_service=artifact_service,
                    run_id="run-4",
                )
            }

            profile = json.loads(
                tools["artifact_profile"].invoke(
                    {"artifact_id": artifact.artifact_id, "top_values_limit": 5}
                )
            )
            self.assertEqual(profile["profile"]["row_count"], 3)
            self.assertEqual(
                profile["profile"]["columns_profile"]["merchant"]["missing_count"],
                1,
            )
            self.assertEqual(
                profile["profile"]["columns_profile"]["event_type"]["top_values"][0],
                {"value": "payment", "count": 2},
            )

            sample = json.loads(
                tools["artifact_sample"].invoke(
                    {"artifact_id": artifact.artifact_id, "offset": 1, "limit": 1}
                )
            )
            self.assertEqual(sample["returned"], 1)
            self.assertEqual(sample["records"][0]["event_id"], "evt-2")

            search = json.loads(
                tools["artifact_search"].invoke(
                    {
                        "artifact_id": artifact.artifact_id,
                        "query": "coffee",
                        "columns": ["merchant"],
                        "limit": 10,
                    }
                )
            )
            self.assertEqual(search["returned"], 2)
            self.assertEqual(search["records"][0]["row_index"], 0)

            counts = json.loads(
                tools["artifact_value_counts"].invoke(
                    {
                        "artifact_id": artifact.artifact_id,
                        "columns": ["event_type", "merchant"],
                        "limit": 10,
                    }
                )
            )
            self.assertEqual(
                counts["counts"][0],
                {
                    "values": {"event_type": "payment", "merchant": "Coffee"},
                    "count": 2,
                },
            )


if __name__ == "__main__":
    unittest.main()
