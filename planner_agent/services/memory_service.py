"""File-backed memory service with frozen run snapshots."""

from __future__ import annotations

from pathlib import Path

from planner_agent.schemas.memory import MemorySnapshot, MemoryTarget, MemoryWriteProposal

from ._json import append_jsonl, compact_text, read_jsonl, write_text_if_missing


class MemoryService:
    FILES: dict[MemoryTarget, str] = {
        "memory": "memory.md",
        "user": "user.md",
        "project": "project.md",
    }

    def __init__(self, memory_dir: str | Path = "memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        for filename in self.FILES.values():
            write_text_if_missing(self.memory_dir / filename)

    def read(self, target: MemoryTarget) -> str:
        return (self.memory_dir / self.FILES[target]).read_text(encoding="utf-8")

    def load_snapshot(self, run_id: str = "") -> MemorySnapshot:
        user = self.read("user")
        memory = self.read("memory")
        project = self.read("project")
        rendered = compact_text(
            [
                self._render_block("USER MEMORY", user),
                self._render_block("PROJECT MEMORY", project),
                self._render_block("GENERAL MEMORY", memory),
            ]
        )
        return MemorySnapshot(run_id=run_id, user=user, memory=memory, project=project, rendered=rendered)

    def propose_write(
        self,
        *,
        target: MemoryTarget,
        content: str,
        rationale: str = "",
        confidence: float = 0.0,
        risk: str = "medium",
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> MemoryWriteProposal:
        proposal = MemoryWriteProposal(
            target=target,
            content=content,
            rationale=rationale,
            confidence=confidence,
            risk=risk,  # type: ignore[arg-type]
            run_id=run_id,
            node_id=node_id,
        )
        append_jsonl(self.memory_dir / "proposals.jsonl", proposal)
        return proposal

    def apply_proposal(self, proposal: MemoryWriteProposal) -> None:
        target_path = self.memory_dir / self.FILES[proposal.target]
        existing = target_path.read_text(encoding="utf-8").strip()
        next_content = compact_text([existing, proposal.content])
        target_path.write_text(next_content + ("\n" if next_content else ""), encoding="utf-8")
        append_jsonl(self.memory_dir / "applied.jsonl", proposal)

    def list_proposals(self) -> list[MemoryWriteProposal]:
        return [
            MemoryWriteProposal.model_validate(row)
            for row in read_jsonl(self.memory_dir / "proposals.jsonl")
        ]

    @staticmethod
    def _render_block(title: str, content: str) -> str:
        if not content.strip():
            return ""
        return f"<{title}>\n{content.strip()}\n</{title}>"


__all__ = ["MemoryService"]
