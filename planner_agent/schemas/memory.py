"""Memory and self-improvement schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


MemoryTarget = Literal["memory", "user", "project"]
ReviewRisk = Literal["low", "medium", "high"]


class MemorySnapshot(BaseModel):
    """Замороженный снимок файлов памяти (user/project/memory) для контекста запуска."""

    snapshot_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str = ""
    user: str = ""
    memory: str = ""
    project: str = ""
    rendered: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryWriteProposal(BaseModel):
    """Предложение изменить долговременную память (вспомогательный контур, не LLM core)."""

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    target: MemoryTarget
    content: str
    rationale: str = ""
    confidence: float = 0.0
    risk: ReviewRisk = "medium"
    run_id: str | None = None
    node_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["MemorySnapshot", "MemoryTarget", "MemoryWriteProposal"]
