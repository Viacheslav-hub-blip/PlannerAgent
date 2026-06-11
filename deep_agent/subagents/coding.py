"""Спецификация coding-subagent.

Содержит функцию:
- build_coding_subagent_spec: сборка capability-aware coding subagent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.coding import GENERAL_PURPOSE_CODING_PROMPT

CODING_AGENT_NAME = "general-purpose"


def build_coding_subagent_spec(
    *,
    model: Any,
    tools: list[Any],
    common_middleware: list[Any],
) -> dict[str, Any]:
    """Собирает спецификацию subagent для ограниченной работы с кодом.

    Args:
        model: Chat-модель LangChain для выполнения coding-задачи.
        tools: Дополнительные инструменты general-purpose subagent.
        common_middleware: Middleware с управлением доступом к workspace tools.

    Returns:
        Словарь спецификации, совместимый с ``create_deep_agent``.
    """

    return {
        "name": CODING_AGENT_NAME,
        "description": (
            "Исследует кодовую базу, планирует работу, делегирует независимые подзадачи "
            "и выполняет coding-задачи без доступа к load_data."
        ),
        "system_prompt": GENERAL_PURPOSE_CODING_PROMPT,
        "model": model,
        "tools": list(tools),
        "middleware": list(common_middleware),
    }
