"""Заглушки LangChain tools для будущей Spark-интеграции.

Модуль предоставляет интерфейсы реальных операций загрузки/чтения/записи данных
через Spark, но пока не выполняет фактические действия. Это позволяет:
- уже сейчас планировать задачи на уровне production-пайплайнов;
- стабилизировать контракты входов/выходов tools;
- позднее заменить внутреннюю реализацию без изменения промптов и планов.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field


class SparkReadTableInput(BaseModel):
    """Вход для чтения таблицы источника в Spark DataFrame."""

    source_system: str = Field(
        description="Имя системы-источника, например dwh, hive, clickhouse, postgres.",
    )
    table: str = Field(
        description="Полное имя таблицы или view, например schema.transactions.",
    )
    where_sql: str = Field(
        default="",
        description="Опциональный SQL-фильтр без ключевого слова WHERE.",
    )
    select_columns: list[str] = Field(
        default_factory=list,
        description="Опциональный список колонок для проекции.",
    )
    limit: int = Field(
        default=0,
        description="Опциональный технический лимит строк (>0) для отладки.",
    )


class SparkReadSqlInput(BaseModel):
    """Вход для исполнения Spark SQL и сохранения результата."""

    sql: str = Field(description="SQL-запрос Spark SQL.")
    result_alias: str = Field(
        default="",
        description="Имя переменной/алиаса результата для повторного использования.",
    )


class SparkWriteDatasetInput(BaseModel):
    """Вход для записи Spark DataFrame в целевое хранилище."""

    dataframe_alias: str = Field(
        description="Имя DataFrame, созданного предыдущими Spark tools.",
    )
    target_uri: str = Field(
        description="Целевой путь/таблица назначения (s3://..., abfs://..., schema.table).",
    )
    format: str = Field(
        default="parquet",
        description="Формат записи: parquet, delta, iceberg, csv, json и т.п.",
    )
    mode: str = Field(
        default="append",
        description="Режим записи: append, overwrite, errorifexists, ignore.",
    )
    partition_by: list[str] = Field(
        default_factory=list,
        description="Опциональные колонки партиционирования.",
    )


class SparkMaterializeArtifactInput(BaseModel):
    """Вход для материализации Spark DataFrame в artifact run-а."""

    dataframe_alias: str = Field(
        description="Имя DataFrame для выгрузки в artifact.",
    )
    artifact_kind: str = Field(
        default="dataset",
        description="Тип artifact (dataset/report/source_excerpt/tool_result).",
    )
    filename: str = Field(
        description="Имя файла artifact, например fraud_transactions.parquet.",
    )
    format: str = Field(
        default="parquet",
        description="Формат выгрузки artifact (parquet/csv/json/jsonl).",
    )


def build_spark_tools() -> list[BaseTool]:
    """Создает набор Spark tool-заглушек с production-контрактами."""

    def spark_read_table(
        source_system: str,
        table: str,
        where_sql: str = "",
        select_columns: list[str] | None = None,
        limit: int = 0,
    ) -> str:
        return _not_implemented_payload(
            tool_name="spark_read_table",
            payload={
                "source_system": source_system,
                "table": table,
                "where_sql": where_sql,
                "select_columns": select_columns or [],
                "limit": limit,
            },
        )

    def spark_read_sql(sql: str, result_alias: str = "") -> str:
        return _not_implemented_payload(
            tool_name="spark_read_sql",
            payload={"sql": sql, "result_alias": result_alias},
        )

    def spark_write_dataset(
        dataframe_alias: str,
        target_uri: str,
        format: str = "parquet",
        mode: str = "append",
        partition_by: list[str] | None = None,
    ) -> str:
        return _not_implemented_payload(
            tool_name="spark_write_dataset",
            payload={
                "dataframe_alias": dataframe_alias,
                "target_uri": target_uri,
                "format": format,
                "mode": mode,
                "partition_by": partition_by or [],
            },
        )

    def spark_materialize_artifact(
        dataframe_alias: str,
        artifact_kind: str = "dataset",
        filename: str = "",
        format: str = "parquet",
    ) -> str:
        return _not_implemented_payload(
            tool_name="spark_materialize_artifact",
            payload={
                "dataframe_alias": dataframe_alias,
                "artifact_kind": artifact_kind,
                "filename": filename,
                "format": format,
            },
        )

    return [
        StructuredTool.from_function(
            func=spark_read_table,
            name="spark_read_table",
            description=(
                "Read a source table into Spark as a reusable dataframe alias. "
                "Use for production data ingestion from governed tables with optional "
                "column projection and SQL filter. This is a contract stub for future "
                "real Spark execution."
            ),
            args_schema=SparkReadTableInput,
        ),
        StructuredTool.from_function(
            func=spark_read_sql,
            name="spark_read_sql",
            description=(
                "Execute Spark SQL over previously loaded data and register result as "
                "a dataframe alias. Use for joins, filters, aggregations and data "
                "quality checks before exporting results. This is a contract stub."
            ),
            args_schema=SparkReadSqlInput,
        ),
        StructuredTool.from_function(
            func=spark_write_dataset,
            name="spark_write_dataset",
            description=(
                "Write a Spark dataframe alias to target storage/table in a specified "
                "format and mode. Use for final data publication to lakehouse/DWH. "
                "This is a contract stub for the future writer implementation."
            ),
            args_schema=SparkWriteDatasetInput,
        ),
        StructuredTool.from_function(
            func=spark_materialize_artifact,
            name="spark_materialize_artifact",
            description=(
                "Export a Spark dataframe alias into the run artifact store so "
                "downstream tasks can inspect or reuse the dataset without rerunning "
                "source extraction. This is a contract stub."
            ),
            args_schema=SparkMaterializeArtifactInput,
        ),
    ]


def _not_implemented_payload(*, tool_name: str, payload: dict[str, Any]) -> str:
    """Возвращает единый ответ для Spark tool-заглушек."""

    return json.dumps(
        {
            "success": False,
            "status": "not_implemented",
            "tool": tool_name,
            "message": (
                "Spark runtime integration is not connected yet. "
                "This tool currently validates contract only."
            ),
            "input": payload,
            "next_step": (
                "Implement Spark session/provider wiring and replace this stub "
                "with real execution logic."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "SparkReadTableInput",
    "SparkReadSqlInput",
    "SparkWriteDatasetInput",
    "SparkMaterializeArtifactInput",
    "build_spark_tools",
]
