"""Тесты локальной интеграции DeepAgent с deep-agents-ui.

Содержит классы:
- LocalUiIntegrationTests: проверка state-маршрута артефактов и примера корзины.

Содержит функции:
- отсутствуют.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepagents.backends import StateBackend

from deep_agent.agent import (
    _normalize_virtual_directory,
    build_skills_backend,
)
from local_ui.example_query import load_basket_query
from run_ui import (
    REQUIRED_FRONTEND_SDK_VERSION,
    _frontend_dependencies_ready,
)


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

    def test_ui_uses_run_model_initialization(self) -> None:
        """Проверяет единый объект модели для консольного запуска и локального UI.

        Returns:
            ``None``. Проверка завершается успешно, если UI импортирует модель,
            используемую консольным entrypoint.
        """

        project_root = Path(__file__).parents[1]
        ui_source = (project_root / "local_ui" / "agent.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("from model import model as run_model", ui_source)
        self.assertIn(
            "build_fake_spark_data_tools(query_parser_model=run_model)",
            ui_source,
        )
        self.assertIn("model=run_model", ui_source)

    def test_frontend_patch_enables_subagent_streaming(self) -> None:
        """Проверяет наличие frontend-контракта для прогресса sub-agents.

        Returns:
            ``None``. Проверка завершается успешно, если patch обновляет SDK,
            связывает sub-agent с сообщением и выводит вложенные tool calls.
        """

        patch_text = (
            Path(__file__).parents[1] / "local_ui" / "deep-agents-ui.local.patch"
        ).read_text(encoding="utf-8")

        self.assertIn('"@langchain/langgraph-sdk": "1.9.21"', patch_text)
        self.assertIn("getSubagentsByMessage", patch_text)
        self.assertIn("streamSubgraphs: true", patch_text)
        self.assertIn("subAgent.toolCalls", patch_text)
        self.assertIn("subAgent.messages", patch_text)

    def test_frontend_dependencies_require_streaming_sdk(self) -> None:
        """Проверяет повторную установку UI при устаревшем frontend SDK.

        Returns:
            ``None``. Проверка завершается успешно только для точной требуемой
            версии ``@langchain/langgraph-sdk``.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            frontend_root = Path(temporary_directory)
            sdk_package = (
                frontend_root
                / "node_modules"
                / "@langchain"
                / "langgraph-sdk"
                / "package.json"
            )
            sdk_package.parent.mkdir(parents=True)
            sdk_package.write_text(
                json.dumps({"version": REQUIRED_FRONTEND_SDK_VERSION}),
                encoding="utf-8",
            )

            with patch("run_ui.FRONTEND_ROOT", frontend_root):
                self.assertTrue(_frontend_dependencies_ready())
                sdk_package.write_text(
                    json.dumps({"version": "1.0.3"}),
                    encoding="utf-8",
                )
                self.assertFalse(_frontend_dependencies_ready())

if __name__ == "__main__":
    unittest.main()
