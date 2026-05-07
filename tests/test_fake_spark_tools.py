"""Тесты Spark-like LangChain tools, читающих CSV из examples/data."""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from examples.fake_spark_tools import (
    TriggerCasesByPeriodInput,
    build_fake_spark_tools,
    build_spark_source_to_sandbox_tool,
)
from sandbox.sandbox import ClientPythonSandbox


class FakeSparkToolsTests(unittest.TestCase):
    """Проверяет Spark-like инструменты."""

    def test_fake_spark_tools_have_basic_tools(self) -> None:
        """Проверяет наличие базовых инструментов."""
        tools = {t.name: t for t in build_fake_spark_tools(delay_seconds=0.0)}
        self.assertEqual(
            set(tools),
            {
                "spark_lookup_trigger_cases",
                "spark_get_trigger_cases_by_period",
                "spark_get_uko_events",
                "spark_get_cards_events",
            },
        )

    def test_spark_source_to_sandbox_preview(self) -> None:
        """Проверяет preview источника через spark_source_to_sandbox."""
        sandbox = ClientPythonSandbox()
        tools = {t.name: t for t in build_spark_source_to_sandbox_tool(sandbox, delay_seconds=0.0)}

        result = asyncio.run(
            tools["spark_source_to_sandbox"].ainvoke({
                "source_name": "source_1",
                "preview": True,
            })
        )

        self.assertEqual(result["mode"], "preview")
        self.assertEqual(result["source_name"], "source_1")
        self.assertEqual(result["source_file"], "source_1.csv")
        self.assertGreater(result["total_rows"], 0)
        self.assertEqual(len(result["rows"]), 5)
        self.assertIn("columns", result)

    def test_spark_source_to_sandbox_load(self) -> None:
        """Проверяет загрузку источника в песочницу через spark_source_to_sandbox."""
        sandbox = ClientPythonSandbox()
        tools = {t.name: t for t in build_spark_source_to_sandbox_tool(sandbox, delay_seconds=0.0)}

        result = asyncio.run(
            tools["spark_source_to_sandbox"].ainvoke({
                "source_name": "source_1",
                "load": True,
                "variable_name": "my_data",
            })
        )

        self.assertEqual(result["mode"], "load")
        self.assertEqual(result["source_name"], "source_1")
        self.assertEqual(result["variable_name"], "my_data")
        self.assertGreater(result["rows_count"], 0)

        # Проверяем, что переменная появилась в песочнице
        var_previews = asyncio.run(sandbox.get_all_variable_previews())
        self.assertIn("my_data", var_previews)

    def test_spark_source_to_sandbox_all_sources(self) -> None:
        """Проверяет загрузку всех трёх источников."""
        sandbox = ClientPythonSandbox()
        tools = {t.name: t for t in build_spark_source_to_sandbox_tool(sandbox, delay_seconds=0.0)}

        for src in ["source_1", "source_2", "source_3"]:
            result = asyncio.run(
                tools["spark_source_to_sandbox"].ainvoke({
                    "source_name": src,
                    "load": True,
                })
            )
            self.assertEqual(result["mode"], "load")

        var_previews = asyncio.run(sandbox.get_all_variable_previews())
        for src in ["source_1", "source_2", "source_3"]:
            var_name = f"df_{src}"
            self.assertIn(var_name, var_previews, f"Missing {var_name}")

    def test_spark_source_to_sandbox_info_mode(self) -> None:
        """Проверяет info-режим (без preview и load)."""
        sandbox = ClientPythonSandbox()
        tools = {t.name: t for t in build_spark_source_to_sandbox_tool(sandbox, delay_seconds=0.0)}

        result = asyncio.run(
            tools["spark_source_to_sandbox"].ainvoke({"source_name": "source_1"})
        )

        self.assertEqual(result["mode"], "info")
        self.assertGreater(result["total_rows"], 0)

    def test_spark_source_to_sandbox_invalid_source(self) -> None:
        """Проверяет ошибку при неверном имени источника."""
        sandbox = ClientPythonSandbox()
        tools = {t.name: t for t in build_spark_source_to_sandbox_tool(sandbox, delay_seconds=0.0)}

        with self.assertRaises(Exception):
            asyncio.run(
                tools["spark_source_to_sandbox"].ainvoke({"source_name": "source_999"})
            )

    def test_spark_get_trigger_cases_by_period_found(self) -> None:
        """Проверяет поиск сработок клиента за период."""
        tools = {t.name: t for t in build_fake_spark_tools(delay_seconds=0.0)}
        result = asyncio.run(
            tools["spark_get_trigger_cases_by_period"].ainvoke({
                "epk_id": "client-42",
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            })
        )

        self.assertIn("found", result)
        self.assertIn("records_count", result)
        self.assertIn("records", result)
        self.assertIn("epk_id", result)
        self.assertEqual(result["epk_id"], "client-42")

    def test_spark_get_trigger_cases_by_period_schema(self) -> None:
        """Проверяет, что TriggerCasesByPeriodInput требует все поля."""
        schema = TriggerCasesByPeriodInput(
            epk_id="client-42",
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
        self.assertEqual(schema.epk_id, "client-42")
        self.assertEqual(schema.start_date, "2025-01-01")
        self.assertEqual(schema.end_date, "2025-01-31")

        with self.assertRaises(Exception):
            TriggerCasesByPeriodInput(epk_id="client-42")


if __name__ == "__main__":
    unittest.main()
