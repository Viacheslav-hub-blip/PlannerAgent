"""Skill schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class SkillRecord(BaseModel):
    """Метаданные одного skill (директория ``skills/<name>/SKILL.md`` и связанные файлы)."""

    name: str
    description: str = ""
    category: str = "general"
    path: str = ""
    tags: list[str] = Field(default_factory=list)
    linked_files: list[str] = Field(default_factory=list)


class SkillPatchProposal(BaseModel):
    """Предложение правки skill (self-improvement / review; не основной runtime-путь)."""

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    skill_name: str
    old_string: str
    new_string: str
    file_path: str | None = None
    rationale: str = ""
    risk: Literal["low", "medium", "high"] = "medium"
    run_id: str | None = None
    node_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["SkillPatchProposal", "SkillRecord"]
