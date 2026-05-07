"""Build AgentState objects for branch/resume execution."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from planner_agent.models import AgentState, Task
from planner_agent.schemas.lineage import StateNode

from .lineage_service import LineageService


class BranchResumeService:
    """Restores a branch run into an AgentState suitable for graph execution."""

    def __init__(self, lineage_service: LineageService) -> None:
        self.lineage_service = lineage_service

    def build_initial_state(
            self,
            *,
            branch_run_id: str,
            branch_node_id: str | None = None,
    ) -> AgentState:
        branch_node = self._resolve_branch_node(
            branch_run_id=branch_run_id,
            branch_node_id=branch_node_id,
        )
        branch_snapshot = self.lineage_service.load_snapshot(
            branch_run_id,
            branch_node.node_id,
        )
        source_snapshot = branch_snapshot.get("source_snapshot") or {}

        new_task = str(branch_snapshot.get("initial_user_query") or "")
        include_completed_tasks = bool(
            branch_snapshot.get("include_completed_tasks", True)
        )
        include_memory_snapshot = bool(
            branch_snapshot.get("include_memory_snapshot", True)
        )

        return AgentState(
            run_id=branch_run_id,
            session_id=str(branch_snapshot.get("session_id") or source_snapshot.get("session_id") or ""),
            user_id=branch_snapshot.get("user_id") or source_snapshot.get("user_id"),
            current_node_id=branch_node.node_id,
            parent_node_ids=[branch_node.node_id],
            messages=[HumanMessage(content=new_task)] if new_task else [],
            initial_user_query=new_task,
            plan=(
                _parse_task_map(source_snapshot.get("plan"))
                if include_completed_tasks
                else {}
            ),
            initial_plan=_parse_task_map(source_snapshot.get("initial_plan")),
            data_schemas=_dict_value(source_snapshot.get("data_schemas")),
            filesystem_context=_dict_value(source_snapshot.get("filesystem_context")),
            skill_previews=_dict_value(source_snapshot.get("skill_previews")),
            memory_snapshot=(
                str(source_snapshot.get("memory_snapshot") or "")
                if include_memory_snapshot
                else ""
            ),
            skills_index=str(source_snapshot.get("skills_index") or ""),
            loaded_skills=_dict_value(source_snapshot.get("loaded_skills")),
            ephemeral_recalls={
                **_dict_value(source_snapshot.get("ephemeral_recalls")),
                "branch_context": _branch_context_text(branch_snapshot, branch_node),
            },
            artifact_index=_dict_value(branch_snapshot.get("artifact_index")),
            task_results=(
                _dict_value(source_snapshot.get("task_results"))
                if include_completed_tasks
                else {}
            ),
            validation_results=(
                _dict_value(source_snapshot.get("validation_results"))
                if include_completed_tasks
                else {}
            ),
            evidence_map=(
                _dict_value(source_snapshot.get("evidence_map"))
                if include_completed_tasks
                else {}
            ),
            lineage_events=[branch_node.model_dump(mode="json")],
        )

    def _resolve_branch_node(
            self,
            *,
            branch_run_id: str,
            branch_node_id: str | None,
    ) -> StateNode:
        if branch_node_id:
            node = self.lineage_service.get_node(branch_run_id, branch_node_id)
            if node is None:
                raise FileNotFoundError(f"Branch node not found: {branch_node_id}")
            return node

        nodes = self.lineage_service.get_nodes(branch_run_id)
        node = next((item for item in nodes if item.node_type == "branch_started"), None)
        if node is None:
            raise FileNotFoundError(f"No branch_started node found in run {branch_run_id}")
        return node


def _parse_task_map(raw: Any) -> dict[str, Task]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, Task] = {}
    for task_id, task_payload in raw.items():
        if isinstance(task_payload, Task):
            parsed[str(task_id)] = task_payload
            continue
        if isinstance(task_payload, dict):
            parsed[str(task_id)] = Task.model_validate(task_payload)
    return parsed


def _dict_value(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _branch_context_text(branch_snapshot: dict[str, Any], branch_node: StateNode) -> str:
    source_run_id = branch_snapshot.get("source_run_id", "")
    source_node_id = branch_snapshot.get("source_node_id", "")
    restored = branch_snapshot.get("restored_artifact_refs") or []
    return (
        f"Branch node: {branch_node.node_id}\n"
        f"Source run: {source_run_id}\n"
        f"Source node: {source_node_id}\n"
        f"Restored artifact refs: {', '.join(restored) if restored else 'none'}"
    )


__all__ = ["BranchResumeService"]
