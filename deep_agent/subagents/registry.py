"""Реестр специализированных subagents.

Содержит функцию:
- build_subagent_specs: формирование списка subagents для supervisor.
"""

from __future__ import annotations

from typing import Any

from deep_agent.subagents.coding import build_coding_subagent_spec
from deep_agent.subagents.data_retrieval import build_data_retrieval_subagent_spec


def build_subagent_specs(
    *,
    data_tools: list[Any],
    general_purpose_tools: list[Any],
    data_retrieval_middleware: list[Any],
    coding_middleware: list[Any],
    model: Any,
) -> list[dict[str, Any]]:
    """Собирает зарегистрированные спецификации subagents.

    Args:
        data_tools: Инструменты чтения данных для data-retrieval-agent.
        general_purpose_tools: Дополнительные инструменты general-purpose subagent.
        data_retrieval_middleware: Middleware data-retrieval-agent.
        coding_middleware: Middleware coding-subagent.
        model: Chat-модель LangChain для обоих subagents.

    Returns:
        Список спецификаций для параметра ``subagents`` фабрики DeepAgent.
    """

    return [
        build_coding_subagent_spec(
            model=model,
            tools=general_purpose_tools,
            common_middleware=coding_middleware,
        ),
        build_data_retrieval_subagent_spec(
            model=model,
            data_tools=data_tools,
            common_middleware=data_retrieval_middleware,
        ),
    ]
