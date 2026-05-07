"""Simple session search over persisted runs."""

from __future__ import annotations

from pathlib import Path

from .lineage_service import LineageService


class SessionService:
    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.lineage = LineageService(runs_dir)

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, str]]:
        terms = {part.lower() for part in query.split() if part.strip()}
        scored: list[tuple[int, dict[str, str]]] = []
        for run in self.lineage.list_runs():
            haystack = f"{run.title} {run.initial_user_query}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append(
                    (
                        score,
                        {
                            "run_id": run.run_id,
                            "title": run.title,
                            "initial_user_query": run.initial_user_query,
                        },
                    )
                )
        return [item for _, item in sorted(scored, key=lambda row: row[0], reverse=True)[:limit]]


__all__ = ["SessionService"]
