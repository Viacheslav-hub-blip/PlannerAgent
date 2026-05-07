"""Policy and audit schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


PolicyVerdict = Literal["allow", "deny", "review"]


class PolicyDecision(BaseModel):
    """Решение политики доступа к tool (allow/deny/review) для аудита и enforcement."""

    decision_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str | None = None
    node_id: str | None = None
    user_id: str | None = None
    tool_name: str
    decision: PolicyVerdict
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["PolicyDecision", "PolicyVerdict"]
