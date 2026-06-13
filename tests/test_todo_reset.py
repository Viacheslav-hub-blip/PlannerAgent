"""Тесты сброса списка задач между пользовательскими запросами.

Содержит классы:
- TodoResetMiddlewareTests: проверка границ пользовательского turn.
"""

from __future__ import annotations

import unittest

from langchain_core.messages import HumanMessage

from deep_agent.middleware.todo_reset import TodoResetMiddleware


class TodoResetMiddlewareTests(unittest.TestCase):
    """Проверяет очистку задач только при начале нового turn."""

    def test_clears_todos_for_first_user_turn(self) -> None:
        """Проверяет очистку старого плана при первом обработанном запросе.

        Returns:
            ``None``.
        """

        middleware = TodoResetMiddleware()
        update = middleware.before_agent(
            {
                "messages": [HumanMessage(content="Новый запрос", id="user-1")],
                "todos": [{"content": "Старая задача", "status": "completed"}],
            },
            None,  # type: ignore[arg-type]
        )

        self.assertEqual(
            update,
            {"todos": [], "todos_user_turn_key": "user-1"},
        )

    def test_keeps_todos_when_same_turn_is_resumed(self) -> None:
        """Проверяет сохранение плана при продолжении того же запроса.

        Returns:
            ``None``.
        """

        middleware = TodoResetMiddleware()
        update = middleware.before_agent(
            {
                "messages": [HumanMessage(content="Запрос", id="user-1")],
                "todos_user_turn_key": "user-1",
                "todos": [{"content": "Текущая задача", "status": "in_progress"}],
            },
            None,  # type: ignore[arg-type]
        )

        self.assertIsNone(update)

    def test_clears_todos_for_new_message_with_same_text(self) -> None:
        """Проверяет границу turn по ID, а не только по тексту запроса.

        Returns:
            ``None``.
        """

        middleware = TodoResetMiddleware()
        update = middleware.before_agent(
            {
                "messages": [HumanMessage(content="Повтори", id="user-2")],
                "todos_user_turn_key": "user-1",
                "todos": [{"content": "Прошлая задача", "status": "completed"}],
            },
            None,  # type: ignore[arg-type]
        )

        self.assertEqual(
            update,
            {"todos": [], "todos_user_turn_key": "user-2"},
        )


if __name__ == "__main__":
    unittest.main()
