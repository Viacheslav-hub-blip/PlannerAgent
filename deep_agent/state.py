"""Расширенный state аналитического DeepAgent для skills middleware.

Содержит:
- AnalyticsAgentState: state агента с приватными полями предзагрузки skills.
- extract_state_messages: извлечение истории сообщений из state.
"""

from __future__ import annotations

from typing import Annotated, Any

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
    postgres_logging_run_id: NotRequired[Annotated[str, PrivateStateAttr]]


def extract_state_messages(state: Any) -> list[Any]:
    """Достаёт список сообщений из state (dict-подобный AgentState или объект).

    Возвращает пустой список, если поле ``messages`` отсутствует или не список.
    Используется middleware, которым нужна история сообщений из ``ToolCallRequest.state``.
    """

    if isinstance(state, dict):
        messages = state.get("messages")
    else:
        messages = getattr(state, "messages", None)
    return messages if isinstance(messages, list) else []


__all__ = ["AnalyticsAgentState", "extract_state_messages"]
