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


if __name__ == "__main__":
    unittest.main()
