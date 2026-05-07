"""Runtime configuration for the research agent backend."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ResearchAgentConfig(BaseModel):
    """Статические лимиты и пути окружения агента (фабрика графа использует свои аргументы)."""

    project_root: Path = Field(default_factory=lambda: Path(".").resolve())
    workspace_root: Path = Field(default_factory=lambda: Path(".").resolve())
    sources_dir: Optional[Path] = None
    contexts_dir: Optional[Path] = None
    skills_dir: Path = Path("skills")
    memory_dir: Path = Path("memory")
    runs_dir: Path = Path("runs")
    max_parallel_tasks: int = 4
    max_retries_per_task: int = 1
    require_human_review_for_shared_skills: bool = True
    allow_internet_tools: bool = False
    allow_raw_shell: bool = False

    def resolve_paths(self) -> "ResearchAgentConfig":
        root = self.project_root.resolve()
        data = self.model_dump()
        for key in ("workspace_root", "skills_dir", "memory_dir", "runs_dir"):
            value = Path(data[key])
            data[key] = value if value.is_absolute() else (root / value).resolve()
        for key in ("sources_dir", "contexts_dir"):
            value = data.get(key)
            if value is None:
                continue
            path = Path(value)
            data[key] = path if path.is_absolute() else (root / path).resolve()
        return ResearchAgentConfig(**data)


__all__ = ["ResearchAgentConfig"]
