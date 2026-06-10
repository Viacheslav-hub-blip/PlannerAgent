"""Тесты локальной интеграции DeepAgent с deep-agents-ui.

Содержит классы:
- LocalUiIntegrationTests: проверка state-маршрута артефактов и примера корзины.
"""

from __future__ import annotations

import unittest

from deepagents.backends import StateBackend

from deep_agent_test.core.analytics_deep_agent import (
    _normalize_virtual_directory,
    build_skills_backend,
)
from local_ui.example_query import load_basket_query


class LocalUiIntegrationTests(unittest.TestCase):
    """Проверяет локальный UI-контракт без запуска модели и внешних API."""

    def test_artifacts_route_uses_langgraph_state(self) -> None:
        """Создаёт backend с текстовыми артефактами в state LangGraph.

        Returns:
            ``None``. Проверка завершается успешно при наличии маршрута
            ``/artifacts/`` на ``StateBackend``.
        """

        backend = build_skills_backend(state_artifacts_virtual_dir="artifacts")

        self.assertEqual(backend.artifacts_root, "/artifacts/")
        self.assertIsInstance(backend.routes["/artifacts/"], StateBackend)

    def test_virtual_artifacts_directory_is_normalized(self) -> None:
        """Нормализует Windows- и POSIX-варианты виртуального пути.

        Returns:
            ``None``. Проверка завершается успешно при едином формате ``/artifacts/``.
        """

        self.assertEqual(_normalize_virtual_directory(r"\artifacts"), "/artifacts/")
        self.assertEqual(_normalize_virtual_directory("/artifacts/"), "/artifacts/")

    def test_example_query_reads_first_basket_case(self) -> None:
        """Читает демонстрационный запрос напрямую из актуальной тестовой корзины.

        Returns:
            ``None``. Проверка завершается успешно, если кейс содержит ожидаемое правило.
        """

        query = load_basket_query("1")

        self.assertIn("DENY оплата обучения после смены устройства", query)


if __name__ == "__main__":
    unittest.main()
