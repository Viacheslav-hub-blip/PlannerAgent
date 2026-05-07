"""Run graph and branching schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
NodeStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]
CreatedBy = Literal["agent", "user", "system"]
BranchMode = Literal["continue", "revise", "alternative", "what_if"]


class ResearchRun(BaseModel):
    """Идентифицируемый запуск исследования: метаданные, статус, связь с ветками."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str = ""
    user_id: str | None = None
    title: str = ""
    initial_user_query: str = ""
    status: RunStatus = "running"
    root_node_id: str | None = None
    parent_run_id: str | None = None
    source_node_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateNode(BaseModel):
    """Узел lineage-графа: тип шага, статус, ссылки на snapshot и артефакты."""

    node_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    parent_ids: list[str] = Field(default_factory=list)
    node_type: str
    status: NodeStatus = "pending"
    title: str
    summary: str = ""
    state_ref: str = ""
    artifact_refs: list[str] = Field(default_factory=list)
    tool_trace_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: CreatedBy = "agent"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BranchRequest(BaseModel):
    """Запрос новой ветки от существующего node/snapshot с новой задачей."""

    source_run_id: str
    source_node_id: str
    new_task: str
    branch_mode: BranchMode
    artifact_refs: list[str] = Field(default_factory=list)
    artifact_overrides: dict[str, str] = Field(default_factory=dict)
    include_artifacts: bool = True
    include_memory_snapshot: bool = True
    include_completed_tasks: bool = True


__all__ = [
    "BranchMode",
    "BranchRequest",
    "CreatedBy",
    "NodeStatus",
    "ResearchRun",
    "RunStatus",
    "StateNode",
]
