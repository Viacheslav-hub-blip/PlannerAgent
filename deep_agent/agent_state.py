"""Расширенный state аналитического DeepAgent для skills middleware.

Содержит:
- AnalyticsAgentState: state агента с приватными полями предзагрузки skills.
"""

from __future__ import annotations

from typing import Annotated

from langchain.agents.middleware import AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from typing_extensions import NotRequired


class AnalyticsAgentState(AgentState):
    """State агента с полями предзагрузки skills."""

    skills_context_loaded: NotRequired[Annotated[bool, PrivateStateAttr]]
    preloaded_skill_paths: NotRequired[Annotated[list[str], PrivateStateAttr]]
    preloaded_skills_context: NotRequired[Annotated[str, PrivateStateAttr]]
    preloaded_skills_selection_user_key: NotRequired[Annotated[str, PrivateStateAttr]]
    preloaded_skills_selection_status: NotRequired[Annotated[str, PrivateStateAttr]]
    preloaded_skills_selection_reason: NotRequired[Annotated[str, PrivateStateAttr]]
    preloaded_skills_selection_error: NotRequired[Annotated[str, PrivateStateAttr]]
    preloaded_skills_selection_retry: NotRequired[Annotated[bool, PrivateStateAttr]]
    preloaded_skills_selection_validation_errors: NotRequired[
        Annotated[list[str], PrivateStateAttr]
    ]
    materialized_skill_paths: NotRequired[Annotated[list[str], PrivateStateAttr]]

__all__ = ["AnalyticsAgentState"]
