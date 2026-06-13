"""Спецификация subagent для получения табличных данных.

Содержит функцию:
- build_data_retrieval_subagent_spec: сборка конфигурации data-retrieval-agent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.data_retrieval import DATA_RETRIEVAL_PROMPT

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"


def build_data_retrieval_subagent_spec(
    *,
    model: Any,
    data_tools: list[Any],
    common_middleware: list[Any],
    skill_sources: list[str],
) -> dict[str, Any]:
    """Собирает спецификацию subagent для чтения табличных данных.

    Args:
        model: Chat-модель LangChain для выполнения запросов subagent.
        data_tools: Инструменты чтения и обработки данных.
        common_middleware: Middleware, подключаемые к subagent.
        skill_sources: Виртуальные каталоги skills для нативного ``SkillsMiddleware``.

    Returns:
        Словарь спецификации, совместимый с ``create_deep_agent``.
    """

    return {
        "name": DATA_RETRIEVAL_AGENT_NAME,
        "description": (
            "Читает табличные данные через load_data и возвращает структурированный "
            "отчет supervisor. Используй для выборок по полям, фильтрам, ключам и периоду."
        ),
        "system_prompt": DATA_RETRIEVAL_PROMPT,
        "model": model,
        "tools": data_tools,
        "skills": list(skill_sources),
        "middleware": list(common_middleware),
    }
