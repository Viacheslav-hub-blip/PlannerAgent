"""Реестр специализированных subagents.

Содержит функцию:
- build_subagent_specs: формирование списка subagents для supervisor.
"""

from __future__ import annotations

from typing import Any

from deep_agent.subagents.coding import CODING_AGENT_NAME


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
            "description": (
                "Исследует workspace и выполняет ограниченные coding-задачи, "
                "изменения файлов и локальные проверки без доступа к load_data."
            ),
            "runnable": coding_agent,
        },
        {
            "name": "data-retrieval-agent",
            "description": (
                "Читает табличные данные через load_data и возвращает supervisor "
                "компактный проверяемый отчёт без доступа к shell."
            ),
            "runnable": data_retrieval_agent,
        },
    ]
