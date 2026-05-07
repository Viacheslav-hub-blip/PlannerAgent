"""Feedback schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserFeedback(BaseModel):
    """Оценка запуска пользователем (like/dislike) для учёта качества в интеграциях."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    rating: Literal["like", "dislike"]
    comment: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["UserFeedback"]
