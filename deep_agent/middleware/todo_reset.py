"""Сброс списка задач при начале нового пользовательского запроса и после ответа.

Содержит классы:
- TodoResetMiddleware: очищение завершённого или незавершённого плана прошлого turn и завершённого run.

Содержит функции:
- _latest_user_turn_key: получение стабильного идентификатора последнего human-сообщения.
- _has_final_ai_message: проверка наличия финального ответа агента.
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime
from typing_extensions import NotRequired

from deep_agent.state import AnalyticsAgentState


class TodoResetState(AnalyticsAgentState):
    """State агента с идентификатором turn, для которого очищен список задач."""

    todos_user_turn_key: NotRequired[Annotated[str, PrivateStateAttr]]


class TodoResetMiddleware(AgentMiddleware[TodoResetState]):
    """Очищает ``todos`` при появлении нового пользовательского сообщения и после финального ответа.

    Resume, approval и продолжение выполнения не создают новое human-сообщение,
    поэтому текущий план в этих сценариях сохраняется до завершения run. После финального
    AI-сообщения список задач сбрасывается, чтобы UI не показывал устаревший план.
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

    def after_agent(
        self,
        state: TodoResetState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Сбрасывает задачи после генерации финального ответа агента.

        Args:
            state: Финальный state с историей сообщений и списком задач.
            runtime: Runtime текущего запуска LangGraph.

        Returns:
            Обновление с пустым списком задач либо ``None``, если финального ответа ещё нет.
        """

        del runtime
        if not state.get("todos"):
            return None
        if not _has_final_ai_message(state):
            return None
        return {"todos": []}

    async def aafter_agent(
        self,
        state: TodoResetState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Асинхронно сбрасывает задачи после генерации финального ответа агента.

        Args:
            state: Финальный state с историей сообщений и списком задач.
            runtime: Runtime текущего запуска LangGraph.

        Returns:
            Обновление с пустым списком задач либо ``None``.
        """

        return self.after_agent(state, runtime)


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


def _has_final_ai_message(state: TodoResetState) -> bool:
    """Проверяет, что в state есть финальное AI-сообщение без ожидающих tool calls.

    Args:
        state: State агента с историей сообщений.

    Returns:
        ``True``, если найден последний содержательный ответ ассистента без tool calls.
    """

    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) or getattr(message, "type", None) == "ai":
            tool_calls = getattr(message, "tool_calls", None) or []
            content = getattr(message, "content", "") or ""
            return not tool_calls and bool(str(content).strip())
    return False


__all__ = ["TodoResetMiddleware", "TodoResetState"]
