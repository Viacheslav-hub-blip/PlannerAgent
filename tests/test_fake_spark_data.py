"""Тесты локального fake-инструмента чтения CSV.

Содержит:
- FakeSparkDataTests: проверки доступности CSV и базовой выборки без LLM.
"""

from __future__ import annotations

import unittest

from deep_agent_test.tools.fake_spark_data import (
    FAKE_DATA_ROOT,
    FAKE_TABLE_FILES,
    _fake_read_table,
    _load_table_frame,
)


class FakeSparkDataTests(unittest.TestCase):
    """Проверяет локальный источник данных без Spark и внешней модели."""

    def test_all_configured_csv_files_exist(self) -> None:
        """Проверяет наличие всех CSV из карты fake-таблиц.

        Returns:
            ``None``. Проверка завершается успешно, если все файлы существуют.
        """

        missing = [
            filename
            for filename in FAKE_TABLE_FILES.values()
            if not (FAKE_DATA_ROOT / filename).is_file()
        ]

        self.assertEqual(missing, [])

    def test_fake_read_table_returns_rows(self) -> None:
        """Выполняет базовую выборку из hits без вызова LLM.

        Returns:
            ``None``. Проверка завершается успешно при непустом DataFrame.
        """

        result = _fake_read_table(
            table_name="hits",
            select_columns=["event_id", "event_dt"],
            filters=[],
            derived_columns=[],
            group_by=[],
            aggregations=[],
            order_by=[],
            max_rows=2,
        )

        self.assertEqual(list(result.columns), ["event_id", "event_dt"])
        self.assertGreater(len(result), 0)
        self.assertLessEqual(len(result), 2)

    def test_long_epk_id_is_loaded_as_string(self) -> None:
        """Проверяет сохранение точности длинного клиентского идентификатора.

        Returns:
            ``None``. Проверка завершается успешно, если ``epk_id`` загружен строкой без изменений.
        """
        table = _load_table_frame("cspfs_repo_features3.hits_extra_info_129372427_view")
        event = table.loc[table["event_id"] == "9c85121b-1819-426e-8db4-28a7f413d5d7"].iloc[0]

        self.assertEqual(event["epk_id"], "2099007770421995000001")

    def test_fake_read_table_filters_long_epk_id(self) -> None:
        """Проверяет фильтрацию hits по длинному строковому ``epk_id``.

        Returns:
            ``None``. Проверка завершается успешно при нахождении десяти сработок клиента.
        """
        result = _fake_read_table(
            table_name="hits",
            select_columns=["event_id", "event_dt", "epk_id", "transaction_amount_in_rub"],
            filters=[
                {
                    "column": "event_dt",
                    "operator": "between",
                    "values": ["20260124", "20260220"],
                },
                {
                    "column": "epk_id",
                    "operator": "eq",
                    "value": "2099007770421995000001",
                },
            ],
            derived_columns=[],
            group_by=[],
            aggregations=[],
            order_by=[],
            max_rows=None,
        )

        self.assertEqual(len(result), 10)
        self.assertEqual(result["epk_id"].nunique(), 1)
        self.assertAlmostEqual(float(result["transaction_amount_in_rub"].sum()), 458116.99, places=2)

    def test_fake_read_table_normalizes_iso_event_dt_period(self) -> None:
        """Проверяет поддержку ISO-дат в фильтре периода по ``event_dt``.

        Returns:
            ``None``. Проверка завершается успешно, если ISO-период корректно применяется
            к числовой колонке ``event_dt``.
        """
        result = _fake_read_table(
            table_name="hits",
            select_columns=["event_id", "event_dt", "main_rule", "transaction_amount_in_rub"],
            filters=[
                {
                    "column": "event_dt",
                    "operator": "between",
                    "values": ["2026-01-24", "2026-02-20"],
                },
                {
                    "column": "main_rule",
                    "operator": "contains",
                    "value": "CARD_DENY крупная покупка образовательных услуг после cash-in",
                },
            ],
            derived_columns=[],
            group_by=[],
            aggregations=[],
            order_by=[],
            max_rows=None,
        )

        self.assertEqual(len(result), 11)
        self.assertAlmostEqual(float(result["transaction_amount_in_rub"].mean()), 98327.18, places=2)


if __name__ == "__main__":
    unittest.main()
