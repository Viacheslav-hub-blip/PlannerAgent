"""LangGraph workflow entrypoint."""

from __future__ import annotations

from typing import Any


def build_research_graph(*args: Any, **kwargs: Any) -> Any:
    """Build the current planner-first LangGraph workflow.

    The implementation stays in ``factory.py`` for now. Keeping this wrapper
    thin preserves a stable v2 module while Phase 1 stabilizes schemas and
    services.
    """

    from .factory import planner_agent

    return planner_agent(*args, **kwargs)


__all__ = ["build_research_graph"]
