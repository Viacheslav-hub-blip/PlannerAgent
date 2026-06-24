"""Спецификация subagent для получения табличных данных.

Содержит функцию:
- build_data_retrieval_subagent_spec: сборка параметров создания data-retrieval-agent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.data_retrieval import DATA_RETRIEVAL_PROMPT

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"
DATA_RETRIEVAL_AGENT_DESCRIPTION = (
    "Use only for bounded table data retrieval with load_data. Good tasks: inspect confirmed table fields, load raw "
    "rows for a known source/period/filter, fetch unique values of one column for later semantic classification, "
    "retrieve rows matching exact identifiers or exact candidate values, and return auditable evidence about source, "
    "fields, period, filters, row count, preview/offload artifact, and limitations. Provide a precise retrieval "
    "objective, source or skill path, required fields, exact period when known, confirmed filters, expected evidence, "
    "and stopping condition. Do not use for calculations, aggregations, grouping, joins after retrieval, semantic "
    "classification decisions, dataframe transformations, chart/report generation, exports, or saving user-facing "
    "artifacts; delegate those follow-up tasks to coding-agent. Bad tasks: calculate totals or averages, transform a "
    "pickle into CSV, classify text values, build a report, or validate a generated file."
)


def build_data_retrieval_subagent_spec(
    *,
    model: Any,
    data_tools: list[Any],
    common_middleware: list[Any],
    skill_sources: list[str],
) -> dict[str, Any]:
    """Собирает параметры создания subagent для чтения табличных данных.

    Args:
        model: Chat-модель LangChain для выполнения запросов subagent.
        data_tools: Инструменты чтения и обработки данных.
        common_middleware: Middleware, подключаемые к subagent.
        skill_sources: Виртуальные каталоги skills для нативного ``SkillsMiddleware``.

    Returns:
        Словарь именованных аргументов, совместимый с ``create_deep_agent``.
    """

    return {
        "name": DATA_RETRIEVAL_AGENT_NAME,
        "system_prompt": DATA_RETRIEVAL_PROMPT,
        "model": model,
        "tools": list(data_tools),
        "skills": list(skill_sources),
        "middleware": list(common_middleware),
    }
