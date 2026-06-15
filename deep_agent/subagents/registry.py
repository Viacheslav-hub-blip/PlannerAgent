"""Реестр специализированных subagents.

Содержит функцию:
- build_subagent_specs: формирование списка subagents для supervisor.
"""

from __future__ import annotations

from typing import Any

from deep_agent.subagents.coding import (
    CODING_AGENT_DESCRIPTION,
    CODING_AGENT_NAME,
)
from deep_agent.subagents.data_retrieval import (
    DATA_RETRIEVAL_AGENT_DESCRIPTION,
    DATA_RETRIEVAL_AGENT_NAME,
)


def build_subagent_specs(
    *,
    coding_agent: Any,
    data_retrieval_agent: Any,
) -> list[dict[str, Any]]:
    """Собирает спецификации изолированных compiled subagents.

    Args:
        coding_agent: Скомпилированный coding-agent с workspace backend.
        data_retrieval_agent: Скомпилированный агент чтения данных без shell.

    Returns:
        Список ``CompiledSubAgent``-совместимых словарей для supervisor.
    """

    return [
        {
            "name": CODING_AGENT_NAME,
            "description": CODING_AGENT_DESCRIPTION,
            "runnable": coding_agent,
        },
        {
            "name": DATA_RETRIEVAL_AGENT_NAME,
            "description": DATA_RETRIEVAL_AGENT_DESCRIPTION,
            "runnable": data_retrieval_agent,
        },
    ]
