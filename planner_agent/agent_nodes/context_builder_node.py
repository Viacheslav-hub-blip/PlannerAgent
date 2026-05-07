"""Context builder node for frozen run context."""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from ..models import AgentState
from ..services.lineage_service import LineageService
from ..services.memory_service import MemoryService
from ..services.skills_service import SkillsService

GOTO_PLANNER = "planner"
CONTEXT_NODE_TYPE = "research_context_built"


async def context_builder_node(
        state: AgentState,
        memory_service: MemoryService | None = None,
        skills_service: SkillsService | None = None,
        lineage_service: LineageService | None = None,
) -> Command:
    """Build startup research context without loading full skills.

    The node freezes durable memory for reproducibility and builds a compact
    skills index for the planner. Full skill content remains out of context
    until worker nodes explicitly need it.
    """

    memory_snapshot = (
        memory_service.load_snapshot(run_id=state.run_id).rendered
        if memory_service is not None
        else state.memory_snapshot
    )
    skills_index = (
        skills_service.build_skills_index()
        if skills_service is not None
        else state.skills_index
    )

    update: dict[str, Any] = {
        "memory_snapshot": memory_snapshot,
        "skills_index": skills_index,
    }

    lineage_event = _create_context_lineage(
        state=state,
        memory_snapshot=memory_snapshot,
        skills_index=skills_index,
        lineage_service=lineage_service,
    )
    if lineage_event:
        update["current_node_id"] = lineage_event["node_id"]
        update["parent_node_ids"] = [lineage_event["node_id"]]
        update["lineage_events"] = [lineage_event]

    return Command(goto=GOTO_PLANNER, update=update)


def _create_context_lineage(
        *,
        state: AgentState,
        memory_snapshot: str,
        skills_index: str,
        lineage_service: LineageService | None,
) -> dict[str, Any] | None:
    if lineage_service is None or not state.run_id:
        return None

    parent_ids = state.parent_node_ids or (
        [state.current_node_id] if state.current_node_id else []
    )
    snapshot = state.model_copy(
        update={
            "memory_snapshot": memory_snapshot,
            "skills_index": skills_index,
            "parent_node_ids": parent_ids,
        },
        deep=True,
    )
    node = lineage_service.create_state_node(
        run_id=state.run_id,
        node_type=CONTEXT_NODE_TYPE,
        title="Research context built",
        parent_ids=parent_ids,
        status="succeeded",
        summary=(
            f"Frozen memory chars: {len(memory_snapshot)}; "
            f"skills index chars: {len(skills_index)}."
        ),
        state=snapshot,
        created_by="system",
        metadata={
            "memory_snapshot_chars": len(memory_snapshot),
            "skills_index_chars": len(skills_index),
            "has_memory_snapshot": bool(memory_snapshot.strip()),
            "has_skills_index": bool(skills_index.strip()),
        },
    )
    return node.model_dump(mode="json")


__all__ = ["context_builder_node"]
