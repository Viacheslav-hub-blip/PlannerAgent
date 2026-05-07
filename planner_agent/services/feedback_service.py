"""Feedback persistence service."""

from __future__ import annotations

from pathlib import Path

from planner_agent.schemas.feedback import UserFeedback

from ._json import append_jsonl, read_jsonl


class FeedbackService:
    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)

    def record_feedback(self, feedback: UserFeedback) -> UserFeedback:
        append_jsonl(self.runs_dir / "feedback.jsonl", feedback)
        if feedback.run_id:
            append_jsonl(self.runs_dir / feedback.run_id / "feedback.jsonl", feedback)
        return feedback

    def list_feedback(self, run_id: str | None = None) -> list[UserFeedback]:
        path = self.runs_dir / run_id / "feedback.jsonl" if run_id else self.runs_dir / "feedback.jsonl"
        return [UserFeedback.model_validate(row) for row in read_jsonl(path)]


__all__ = ["FeedbackService"]
