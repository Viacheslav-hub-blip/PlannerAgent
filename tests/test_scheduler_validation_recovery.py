"""Тесты восстановления задач scheduler-а.

Содержит:
- SchedulerValidationRecoveryTests: проверки маршрутизации зависших задач.
"""

from __future__ import annotations

import unittest
from asyncio import run

from planner_agent.agent_nodes.scheduler_node import scheduler_node
from planner_agent.models import AgentState, Task, TaskStatus


class SchedulerValidationRecoveryTests(unittest.TestCase):
    """Проверки восстановления задач, зависших перед validator."""

    def test_scheduler_routes_needs_validation_task_to_validator(self) -> None:
        """Проверяет, что scheduler не завершает граф при needs_validation.

        Args:
            self: Экземпляр тестового случая.

        Returns:
            ``None``. Тест проверяет маршрут команды scheduler-а.
        """

        state = AgentState(
            run_id="run-1",
            plan={
                "1": Task(
                    task_id="1",
                    description="Получить данные",
                    status=TaskStatus.NEEDS_VALIDATION,
                    result_preview="Данные получены.",
                ),
                "2": Task(
                    task_id="2",
                    description="Использовать данные",
                    dependencies=["1"],
                    status=TaskStatus.PENDING,
                ),
            },
        )

        command = run(scheduler_node(state))

        self.assertIsInstance(command.goto, list)
        self.assertEqual(len(command.goto), 1)
        self.assertEqual(command.goto[0].node, "validator")
        self.assertEqual(command.goto[0].arg.task.task_id, "1")


if __name__ == "__main__":
    unittest.main()
