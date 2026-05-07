"""Hermes-style self-improvement loop for other agent stacks.

The key Hermes techniques copied here:

1. Memory review and skill review are decoupled from the main turn.
2. Review runs after the user already received the answer.
3. Reviews are triggered by nudge counters rather than every turn.
4. The review worker acts through the same stores/tools as the main agent.

This module does not hardcode any LLM SDK. Instead, you provide a review
planner callback that translates a conversation snapshot into review actions.
That makes it easy to embed into LangChain chains, LangGraph nodes, or a
custom orchestration loop.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol

logger = logging.getLogger(__name__)


ReviewActionKind = Literal[
    "memory_add",
    "memory_replace",
    "memory_remove",
    "skill_create",
    "skill_edit",
    "skill_patch",
    "skill_delete",
    "skill_write_file",
    "skill_remove_file",
]


@dataclass(slots=True)
class ReviewAction:
    """Action emitted by a background review planner."""

    kind: ReviewActionKind
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReviewConfig:
    """Copy of Hermes' nudge policy, expressed as portable config."""

    memory_nudge_interval: int = 10
    skill_nudge_interval: int = 10
    max_review_iterations: int = 8


class ReviewPlanner(Protocol):
    """Callable protocol for the background review LLM wrapper."""

    def __call__(
        self,
        *,
        messages_snapshot: List[Dict[str, Any]],
        review_prompt: str,
        max_iterations: int,
    ) -> List[ReviewAction]:
        ...


MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves - their persona, desires, "
    "preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave, their work "
    "style, or ways they want you to operate?\n\n"
    "If something stands out, save it using the memory system. "
    "If nothing is worth saving, return no actions."
)

SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that required trial "
    "and error, changing course due to experiential findings, or a reusable workflow?\n\n"
    "If a relevant skill already exists, update it with what was learned. "
    "Otherwise, create a new skill if the approach is reusable. "
    "If nothing is worth saving, return no actions."
)

COMBINED_REVIEW_PROMPT = (
    "Review the conversation above and consider two things:\n\n"
    "Memory: did the user reveal preferences, identity, expectations, or durable context "
    "worth saving?\n\n"
    "Skills: was a reusable, non-trivial workflow discovered, corrected, or improved?\n\n"
    "Only act if there is something genuinely worth saving. "
    "If nothing stands out, return no actions."
)


def build_review_prompt(*, review_memory: bool, review_skills: bool) -> str:
    if review_memory and review_skills:
        return COMBINED_REVIEW_PROMPT
    if review_memory:
        return MEMORY_REVIEW_PROMPT
    return SKILL_REVIEW_PROMPT


class ReviewNudger:
    """Tracks Hermes-style nudge counters for memory and skill review."""

    def __init__(self, config: ReviewConfig) -> None:
        self.config = config
        self.turns_since_memory = 0
        self.iters_since_skill = 0

    def on_user_turn(self, *, memory_tool_available: bool = True) -> bool:
        """Increment the memory nudge counter and return whether to review."""

        if self.config.memory_nudge_interval <= 0 or not memory_tool_available:
            return False
        self.turns_since_memory += 1
        if self.turns_since_memory >= self.config.memory_nudge_interval:
            self.turns_since_memory = 0
            return True
        return False

    def on_tool_iteration(self, *, skill_tool_available: bool = True) -> None:
        """Increment the skill nudge counter during tool-heavy turns."""

        if self.config.skill_nudge_interval <= 0 or not skill_tool_available:
            return
        self.iters_since_skill += 1

    def on_tool_used(self, tool_name: str) -> None:
        """Reset relevant counters when the agent already wrote memory/skills."""

        if tool_name == "memory":
            self.turns_since_memory = 0
        elif tool_name in {"skill_manage", "skill_create", "skill_patch"}:
            self.iters_since_skill = 0

    def should_review_skills(self, *, skill_tool_available: bool = True) -> bool:
        if self.config.skill_nudge_interval <= 0 or not skill_tool_available:
            return False
        if self.iters_since_skill >= self.config.skill_nudge_interval:
            self.iters_since_skill = 0
            return True
        return False


class BackgroundReviewer:
    """Runs Hermes-style post-turn review in a background thread."""

    def __init__(
        self,
        *,
        planner: ReviewPlanner,
        memory_store: Any | None = None,
        skills_store: Any | None = None,
        config: Optional[ReviewConfig] = None,
    ) -> None:
        self.planner = planner
        self.memory_store = memory_store
        self.skills_store = skills_store
        self.config = config or ReviewConfig()

    def spawn_review(
        self,
        *,
        messages_snapshot: List[Dict[str, Any]],
        review_memory: bool = False,
        review_skills: bool = False,
    ) -> threading.Thread:
        """Spawn a best-effort background review worker."""

        prompt = build_review_prompt(review_memory=review_memory, review_skills=review_skills)

        def _run() -> None:
            try:
                actions = self.planner(
                    messages_snapshot=messages_snapshot,
                    review_prompt=prompt,
                    max_iterations=self.config.max_review_iterations,
                )
                self.apply_actions(actions)
            except Exception:
                logger.warning("Background review failed", exc_info=True)

        thread = threading.Thread(target=_run, name="background-review", daemon=True)
        thread.start()
        return thread

    def apply_actions(self, actions: List[ReviewAction]) -> List[Dict[str, Any]]:
        """Apply review actions against the configured stores."""

        results: List[Dict[str, Any]] = []
        for action in actions:
            try:
                results.append(self._apply_action(action))
            except Exception as exc:
                logger.warning("Review action %s failed", action.kind, exc_info=True)
                results.append({"success": False, "action": action.kind, "error": str(exc)})
        return results

    def _apply_action(self, action: ReviewAction) -> Dict[str, Any]:
        payload = dict(action.payload)

        if action.kind.startswith("memory_"):
            if self.memory_store is None:
                return {"success": False, "action": action.kind, "error": "No memory_store configured."}
            target = payload.get("target", "memory")
            if action.kind == "memory_add":
                result = self.memory_store.add(target, payload["content"])
            elif action.kind == "memory_replace":
                result = self.memory_store.replace(target, payload["old_text"], payload["new_content"])
            elif action.kind == "memory_remove":
                result = self.memory_store.remove(target, payload["old_text"])
            else:
                raise ValueError(f"Unsupported memory action: {action.kind}")
            result["action"] = action.kind
            return result

        if action.kind.startswith("skill_"):
            if self.skills_store is None:
                return {"success": False, "action": action.kind, "error": "No skills_store configured."}
            if action.kind == "skill_create":
                result = self.skills_store.create_skill(
                    payload["name"],
                    payload["content"],
                    payload.get("category"),
                )
            elif action.kind == "skill_edit":
                result = self.skills_store.edit_skill(payload["name"], payload["content"])
            elif action.kind == "skill_patch":
                result = self.skills_store.patch_skill(
                    payload["name"],
                    payload["old_string"],
                    payload["new_string"],
                    file_path=payload.get("file_path"),
                    replace_all=bool(payload.get("replace_all", False)),
                )
            elif action.kind == "skill_delete":
                result = self.skills_store.delete_skill(payload["name"])
            elif action.kind == "skill_write_file":
                result = self.skills_store.write_file(
                    payload["name"],
                    payload["file_path"],
                    payload["file_content"],
                )
            elif action.kind == "skill_remove_file":
                result = self.skills_store.remove_file(payload["name"], payload["file_path"])
            else:
                raise ValueError(f"Unsupported skill action: {action.kind}")
            result["action"] = action.kind
            return result

        raise ValueError(f"Unknown review action kind: {action.kind}")

