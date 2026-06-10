"""Сборка специализированных subagents аналитического coding-agent.

Содержит:
- build_data_retrieval_subagent_spec: спецификация ``data-retrieval-agent``.
- build_general_purpose_subagent_spec: capability-aware coding subagent.
- build_analytics_subagent_specs: список subagents для supervisor-а.
"""

from __future__ import annotations

from typing import Any

from deep_agent_test.core.prompts import DATA_RETRIEVAL_PROMPT, GENERAL_PURPOSE_CODING_PROMPT

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"
GENERAL_PURPOSE_AGENT_NAME = "general-purpose"


def build_data_retrieval_subagent_spec(
    *,
    model: Any,
    data_tools: list[Any],
    common_middleware: list[Any],
) -> dict[str, Any]:
    """Собирает спецификацию ``data-retrieval-agent``.

    Args:
        model: Chat model для data-retrieval-agent.
        data_tools: Инструменты чтения и обработки данных, доступные subagent-у.
        common_middleware: Middleware, применяемые к data-retrieval-agent.

    Returns:
        Словарь спецификации subagent-а для ``create_deep_agent``.
    """

    return {
        "name": DATA_RETRIEVAL_AGENT_NAME,
        "description": (
            "Читает табличные данные через load_data и возвращает структурированный "
            "отчёт supervisor-у. Используй для выборок по полям, фильтрам, ключам и периоду."
        ),
        "system_prompt": DATA_RETRIEVAL_PROMPT,
        "model": model,
        "tools": data_tools,
        "middleware": list(common_middleware),
    }


def build_analytics_subagent_specs(
    *,
    data_tools: list[Any],
    data_retrieval_middleware: list[Any],
    general_purpose_middleware: list[Any],
    model: Any,
) -> list[dict[str, Any]]:
    """Собирает список спеков subagents supervisor-а.

    Args:
        data_tools: Инструменты чтения данных для data-retrieval-agent.
        data_retrieval_middleware: Middleware data-retrieval-agent.
        general_purpose_middleware: Middleware coding subagent.
        model: Chat model для subagent-а.

    Returns:
        Список спеков subagents для ``create_deep_agent(subagents=...)``.
    """

    return [
        build_general_purpose_subagent_spec(
            model=model,
            common_middleware=general_purpose_middleware,
        ),
        build_data_retrieval_subagent_spec(
            model=model,
            data_tools=data_tools,
            common_middleware=data_retrieval_middleware,
        ),
    ]


def build_general_purpose_subagent_spec(
    *,
    model: Any,
    common_middleware: list[Any],
) -> dict[str, Any]:
    """Собирает capability-aware ``general-purpose`` coding subagent.

    Args:
        model: Chat model для coding subagent.
        common_middleware: Middleware с динамической видимостью workspace tools.

    Returns:
        Спецификация subagent, инструменты которого открываются skill
        ``code-workspace``.
    """

    return {
        "name": GENERAL_PURPOSE_AGENT_NAME,
        "description": (
            "Исследует кодовую базу и выполняет ограниченную coding-задачу. "
            "Используй только когда загружен skill code-workspace и полезно вынести "
            "поиск, проверку или отдельную реализацию из основного контекста."
        ),
        "system_prompt": GENERAL_PURPOSE_CODING_PROMPT,
        "model": model,
        "tools": [],
        "middleware": list(common_middleware),
    }


__all__ = [
    "DATA_RETRIEVAL_AGENT_NAME",
    "GENERAL_PURPOSE_AGENT_NAME",
    "build_analytics_subagent_specs",
    "build_data_retrieval_subagent_spec",
    "build_general_purpose_subagent_spec",
]
