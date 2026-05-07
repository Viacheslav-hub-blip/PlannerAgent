from __future__ import annotations

import unittest
from asyncio import run

from langchain_core.messages import HumanMessage

from planner_agent.chat_runner import (
    build_chat_initial_state,
    run_agent_from_state,
    run_chat_agent,
)
from planner_agent.models import AgentState


class FakeGraph:
    async def ainvoke(self, state: AgentState, config: dict | None = None) -> dict:
        return {
            "run_id": state.run_id or "run-chat-1",
            "session_id": state.session_id,
            "user_id": state.user_id,
            "messages": state.messages,
            "initial_user_query": state.initial_user_query,
            "filesystem_context": state.filesystem_context,
            "final_report": f"Report for: {state.initial_user_query}",
        }


class ChatRunnerTests(unittest.TestCase):
    def test_build_chat_initial_state_is_not_ui_or_branch_dependent(self) -> None:
        state = build_chat_initial_state(
            "Find insights",
            session_id="session-1",
            user_id="user-1",
            filesystem_context={"workspace_root": "workspace"},
        )

        self.assertEqual(state.initial_user_query, "Find insights")
        self.assertEqual(state.session_id, "session-1")
        self.assertEqual(state.user_id, "user-1")
        self.assertEqual(state.filesystem_context, {"workspace_root": "workspace"})
        self.assertEqual(len(state.messages), 1)
        self.assertIsInstance(state.messages[0], HumanMessage)
        self.assertEqual(state.messages[0].content, "Find insights")
        self.assertEqual(state.parent_node_ids, [])
        self.assertEqual(state.artifact_index, {})

    def test_run_chat_agent_returns_compact_result(self) -> None:
        result = run(
            run_chat_agent(
                FakeGraph(),
                "Analyze client behavior",
                session_id="session-2",
                user_id="user-2",
            )
        )

        self.assertEqual(result.run_id, "run-chat-1")
        self.assertEqual(result.state.session_id, "session-2")
        self.assertEqual(result.state.user_id, "user-2")
        self.assertEqual(result.final_report, "Report for: Analyze client behavior")

    def test_run_agent_from_state_supports_prepared_state(self) -> None:
        state = AgentState(
            run_id="prepared-run",
            initial_user_query="Continue from prepared state",
            messages=[HumanMessage(content="Continue from prepared state")],
            artifact_index={"artifact-1": {"uri": "transactions.csv"}},
        )

        result = run(run_agent_from_state(FakeGraph(), state))

        self.assertEqual(result.run_id, "prepared-run")
        self.assertEqual(result.state.artifact_index, {"artifact-1": {"uri": "transactions.csv"}})
        self.assertEqual(result.final_report, "Report for: Continue from prepared state")


if __name__ == "__main__":
    unittest.main()
