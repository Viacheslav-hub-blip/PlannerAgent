"""Сброс списка задач при начале нового пользовательского запроса.

Содержит классы:
- TodoResetMiddleware: очищение завершённого или незавершённого плана прошлого turn.

Содержит функции:
- _latest_user_turn_key: получение стабильного идентификатора последнего human-сообщения.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime
from typing_extensions import NotRequired

from deep_agent.state import AnalyticsAgentState


class TodoResetState(AnalyticsAgentState):
    """State агента с идентификатором turn, для которого очищен список задач."""

    todos_user_turn_key: NotRequired[Annotated[str, PrivateStateAttr]]


class TodoResetMiddleware(AgentMiddleware[TodoResetState]):
    """Очищает ``todos`` при появлении нового пользовательского сообщения.

    Resume, approval и продолжение выполнения не создают новое human-сообщение,
    поэтому текущий план в этих сценариях сохраняется.
    """

    state_schema = TodoResetState

    def before_agent(
        self,
        state: TodoResetState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Сбрасывает задачи прошлого turn перед запуском агента.

        Args:
            state: Текущий state с историей сообщений и списком задач.
            runtime: Runtime текущего запуска LangGraph.

        Returns:
            Обновление с пустым списком задач для нового turn либо ``None``.
        """

        del runtime
        user_turn_key = _latest_user_turn_key(state)
        if not user_turn_key:
            return None
        if state.get("todos_user_turn_key") == user_turn_key:
            return None
        return {
            "todos": [],
            "todos_user_turn_key": user_turn_key,
        }


def _latest_user_turn_key(state: TodoResetState) -> str:
    """Возвращает идентификатор последнего пользовательского сообщения.

    Args:
        state: State агента с историей сообщений.

    Returns:
        ID последнего human-сообщения или его текстовый fallback.
    """

    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage) or getattr(message, "type", None) == "human":
            message_id = getattr(message, "id", None)
            if message_id:
                return str(message_id)
            return f"content:{getattr(message, 'content', '')}"
    return ""


__all__ = ["TodoResetMiddleware", "TodoResetState"]
