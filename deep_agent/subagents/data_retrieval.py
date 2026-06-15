"""Спецификация subagent для получения табличных данных.

Содержит функцию:
- build_data_retrieval_subagent_spec: сборка параметров создания data-retrieval-agent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.data_retrieval import DATA_RETRIEVAL_PROMPT

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"
DATA_RETRIEVAL_AGENT_DESCRIPTION = (
    "Читает табличные данные через load_data и возвращает supervisor компактный проверяемый отчёт "
    "по полям, фильтрам, ключам и периоду без доступа к shell."
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
