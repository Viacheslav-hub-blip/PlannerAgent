"""Расширенный state аналитического DeepAgent для skills middleware."""

from __future__ import annotations

from langchain.agents.middleware import AgentState
from typing_extensions import NotRequired


class AnalyticsAgentState(AgentState):
    """State агента с полями предзагрузки skills."""

    skills_context_loaded: NotRequired[bool]
    preloaded_skill_paths: NotRequired[list[str]]
    preloaded_skills_index: NotRequired[list[dict[str, str]]]
    preloaded_skills_context: NotRequired[str]
    preloaded_skills_selection_user_key: NotRequired[str]


__all__ = ["AnalyticsAgentState"]
