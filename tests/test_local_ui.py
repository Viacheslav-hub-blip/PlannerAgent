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

from deepagents.backends import StateBackend

from deep_agent.agent import (
    _normalize_virtual_directory,
    build_supervisor_backend,
)
from deep_agent.entrypoints.validation_query import load_basket_query
from run_ui import (
    REQUIRED_FRONTEND_SDK_VERSION,
    _validate_frontend,
)


class LocalUiIntegrationTests(unittest.TestCase):
    """Проверяет локальный UI-контракт без запуска модели и внешних API."""

    def test_artifacts_route_uses_langgraph_state(self) -> None:
        """Создаёт backend с текстовыми артефактами в state LangGraph.

        Returns:
            ``None``. Проверка завершается успешно при наличии маршрута
            ``/artifacts/`` на ``StateBackend``.
        """

        backend = build_supervisor_backend(state_artifacts_virtual_dir="artifacts")

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

    def test_langgraph_config_points_to_deep_agent_entrypoint(self) -> None:
        """Проверяет, что UI запускает agent entrypoint из слоя ``deep_agent``.

        Returns:
            ``None``. Проверка завершается успешно, если ``langgraph.json``
            указывает на новый Python entrypoint вне ``local_ui``.
        """

        project_root = Path(__file__).parents[1]
        config = json.loads(
            (project_root / "local_ui" / "langgraph.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            config["graphs"]["analytics-agent"],
            "./deep_agent/entrypoints/local_ui.py:agent",
        )

    def test_local_ui_has_no_project_python_files(self) -> None:
        """Проверяет, что ``local_ui`` не содержит authored Python-инициализацию.

        Returns:
            ``None``. Проверка завершается успешно, если Python-слой агента
            перенесён в ``deep_agent``.
        """

        project_root = Path(__file__).parents[1]
        python_files = sorted(
            path.name
            for path in (project_root / "local_ui").glob("*.py")
            if path.is_file()
        )

        self.assertEqual(python_files, [])

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
        self.assertIn("switchThread", patch_text)
        self.assertIn("stream.interrupts", patch_text)
        self.assertIn("subAgent.interrupts", patch_text)

    def test_langgraph_config_does_not_require_env_file(self) -> None:
        """Проверяет запуск UI с Python-конфигурацией без env-файла.

        Returns:
            ``None``.
        """

        config = json.loads(
            (Path(__file__).parents[1] / "local_ui" / "langgraph.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn("env", config)

    def test_frontend_dependencies_require_streaming_sdk(self) -> None:
        """Проверяет повторную установку UI при устаревшем frontend SDK.

        Returns:
            ``None``. Проверка завершается успешно только для точной требуемой
            версии ``@langchain/langgraph-sdk``.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            frontend_root = Path(temporary_directory)
            (frontend_root / "package.json").write_text("{}", encoding="utf-8")
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

            _validate_frontend(frontend_root, strict_sdk=True)
            sdk_package.write_text(
                json.dumps({"version": "1.0.3"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "ожидалась"):
                _validate_frontend(frontend_root, strict_sdk=True)

    def test_offline_installer_uses_archive_and_checksum(self) -> None:
        """Проверяет offline-установку UI без устаревшего ``--install-only``.

        Returns:
            ``None``.
        """

        project_root = Path(__file__).parents[1]
        installer = (project_root / "local_ui" / "install.ps1").read_text(
            encoding="utf-8"
        )
        readme = (project_root / "local_ui" / "README.md").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("--install-only", installer)
        self.assertNotIn("--install-only", readme)
        self.assertIn("SHA256SUMS", installer)
        self.assertIn("Join-ArchiveParts", installer)
        self.assertIn("deep-agents-ui-node20-linux-x86_64.tar.gz", installer)

if __name__ == "__main__":
    unittest.main()
