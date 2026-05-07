"""File-backed lineage service for ResearchRun and StateNode records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from planner_agent.schemas.lineage import BranchRequest, ResearchRun, StateNode

from ._json import append_jsonl, read_json, read_jsonl, to_jsonable, write_json
from .artifact_service import ArtifactService


class LineageService:
    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        *,
        initial_user_query: str,
        session_id: str = "",
        user_id: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        source_node_id: str | None = None,
    ) -> ResearchRun:
        run = ResearchRun(
            session_id=session_id,
            user_id=user_id,
            title=title or self._title_from_query(initial_user_query),
            initial_user_query=initial_user_query,
            parent_run_id=parent_run_id,
            source_node_id=source_node_id,
            metadata=metadata or {},
        )
        self._run_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        write_json(self._run_path(run.run_id), run)
        return run

    def update_run(self, run: ResearchRun) -> ResearchRun:
        run.updated_at = datetime.now(timezone.utc)
        write_json(self._run_path(run.run_id), run)
        return run

    def create_state_node(
        self,
        *,
        run_id: str,
        node_type: str,
        title: str,
        parent_ids: list[str] | None = None,
        status: str = "succeeded",
        summary: str = "",
        state: Any | None = None,
        artifact_refs: list[str] | None = None,
        tool_trace_refs: list[str] | None = None,
        created_by: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> StateNode:
        node = StateNode(
            run_id=run_id,
            parent_ids=parent_ids or [],
            node_type=node_type,
            status=status,  # type: ignore[arg-type]
            title=title,
            summary=summary,
            artifact_refs=artifact_refs or [],
            tool_trace_refs=tool_trace_refs or [],
            created_by=created_by,  # type: ignore[arg-type]
            metadata=metadata or {},
        )
        return self.append_node(node, state=state)

    def append_node(self, node: StateNode, state: Any | None = None) -> StateNode:
        if state is not None and not node.state_ref:
            node.state_ref = str(Path("snapshots") / f"{node.node_id}.json")
            write_json(self._run_dir(node.run_id) / node.state_ref, self._snapshot_payload(state))

        append_jsonl(self._lineage_path(node.run_id), node)

        run = self.get_run(node.run_id)
        if run and run.root_node_id is None:
            run.root_node_id = node.node_id
            self.update_run(run)
        return node

    def get_run(self, run_id: str) -> ResearchRun | None:
        raw = read_json(self._run_path(run_id))
        return ResearchRun.model_validate(raw) if raw else None

    def list_runs(self) -> list[ResearchRun]:
        runs: list[ResearchRun] = []
        for run_json in sorted(self.runs_dir.glob("*/run.json")):
            raw = read_json(run_json)
            if raw:
                runs.append(ResearchRun.model_validate(raw))
        return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def get_nodes(self, run_id: str) -> list[StateNode]:
        return [StateNode.model_validate(row) for row in read_jsonl(self._lineage_path(run_id))]

    def get_node(self, run_id: str, node_id: str) -> StateNode | None:
        return next((node for node in self.get_nodes(run_id) if node.node_id == node_id), None)

    def load_snapshot(self, run_id: str, node_id: str) -> dict[str, Any]:
        node = self.get_node(run_id, node_id)
        if node is None or not node.state_ref:
            raise FileNotFoundError(f"No snapshot found for node {node_id}")
        raw = read_json(self._run_dir(run_id) / node.state_ref)
        if raw is None:
            raise FileNotFoundError(node.state_ref)
        return raw

    def branch_from(self, request: BranchRequest) -> ResearchRun:
        source = self.get_run(request.source_run_id)
        if source is None:
            raise FileNotFoundError(f"Run not found: {request.source_run_id}")
        source_node = self.get_node(request.source_run_id, request.source_node_id)
        if source_node is None:
            raise FileNotFoundError(f"Node not found: {request.source_node_id}")

        branch = self.create_run(
            initial_user_query=request.new_task,
            session_id=source.session_id,
            user_id=source.user_id,
            title=f"Branch: {self._title_from_query(request.new_task)}",
            parent_run_id=source.run_id,
            source_node_id=source_node.node_id,
            metadata={
                "branch_mode": request.branch_mode,
                "include_artifacts": request.include_artifacts,
                "include_memory_snapshot": request.include_memory_snapshot,
                "include_completed_tasks": request.include_completed_tasks,
            },
        )
        branch_node = StateNode(
            run_id=branch.run_id,
            node_type="branch_started",
            title="Branch started",
            status="succeeded",
            summary=f"Branched from {source.run_id}:{source_node.node_id}",
            created_by="user",
            metadata={
                "source_run_id": source.run_id,
                "source_node_id": source_node.node_id,
                "branch_mode": request.branch_mode,
            },
        )
        branch_artifacts = []
        if request.include_artifacts:
            source_artifact_ids = request.artifact_refs or source_node.artifact_refs
            branch_artifacts = ArtifactService(self.runs_dir).register_branch_artifacts(
                source_run_id=source.run_id,
                target_run_id=branch.run_id,
                target_node_id=branch_node.node_id,
                artifact_ids=source_artifact_ids,
                uri_overrides=request.artifact_overrides,
            )
            branch_node.artifact_refs = [
                artifact.artifact_id for artifact in branch_artifacts
            ]

        artifact_index = {
            artifact.artifact_id: artifact.model_dump(mode="json")
            for artifact in branch_artifacts
        }
        branch_snapshot = {
            "run_id": branch.run_id,
            "initial_user_query": request.new_task,
            "source_run_id": source.run_id,
            "source_node_id": source_node.node_id,
            "branch_mode": request.branch_mode,
            "session_id": source.session_id,
            "user_id": source.user_id,
            "include_artifacts": request.include_artifacts,
            "include_memory_snapshot": request.include_memory_snapshot,
            "include_completed_tasks": request.include_completed_tasks,
            "artifact_index": artifact_index,
            "restored_artifact_refs": branch_node.artifact_refs,
        }
        try:
            branch_snapshot["source_snapshot"] = self.load_snapshot(
                source.run_id,
                source_node.node_id,
            )
        except FileNotFoundError:
            branch_snapshot["source_snapshot"] = {}

        self.append_node(branch_node, state=branch_snapshot)
        return branch

    def _lineage_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "lineage.jsonl"

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    @staticmethod
    def _snapshot_payload(state: Any) -> Any:
        if isinstance(state, BaseModel):
            return state.model_dump(mode="json")
        return to_jsonable(state)

    @staticmethod
    def _title_from_query(query: str) -> str:
        compact = " ".join(query.split())
        return compact[:80] if compact else f"Research run {uuid4().hex[:8]}"


__all__ = ["LineageService"]
