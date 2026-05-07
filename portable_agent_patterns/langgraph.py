"""Optional LangGraph-oriented helpers.

The helpers here do not require LangGraph at import time. They simply create
plain Python node callables that operate on a dict-like state, which makes
them easy to plug into StateGraph.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from portable_agent_patterns.memory import build_memory_context_block


def make_prefetch_memory_node(memory_manager: Any) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Create a node that prefetches memory for the current user message."""

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        user_message = str(state.get("user_message", ""))
        session_id = str(state.get("session_id", ""))
        recalled = memory_manager.prefetch_all(user_message, session_id=session_id)
        return {
            **state,
            "memory_context": recalled,
            "memory_context_block": build_memory_context_block(recalled),
        }

    return _node


def make_post_turn_review_node(
    reviewer: Any,
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Create a node that spawns Hermes-style background review."""

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        final_response = state.get("final_response")
        interrupted = bool(state.get("interrupted", False))
        if not final_response or interrupted:
            return state

        reviewer.spawn_review(
            messages_snapshot=list(state.get("messages", [])),
            review_memory=bool(state.get("review_memory", False)),
            review_skills=bool(state.get("review_skills", False)),
        )
        return state

    return _node


def make_counter_update_node(nudger: Any) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Create a node that updates Hermes-style nudge counters."""

    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        review_memory = nudger.on_user_turn(
            memory_tool_available=bool(state.get("memory_tool_available", True))
        )
        review_skills = nudger.should_review_skills(
            skill_tool_available=bool(state.get("skill_tool_available", True))
        )
        return {
            **state,
            "review_memory": review_memory,
            "review_skills": review_skills,
        }

    return _node

