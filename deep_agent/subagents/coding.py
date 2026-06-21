"""Спецификация coding-subagent.

Содержит функцию:
- build_coding_subagent_spec: сборка параметров создания coding-agent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.coding import CODING_AGENT_PROMPT

CODING_AGENT_NAME = "coding-agent"
CODING_AGENT_DESCRIPTION = (
    "Use for bounded code and workspace file tasks: inspect a repository, refactor existing code, edit or create "
    "source files, tests, prompts, skills, documentation, configuration, notebooks, and other text artifacts; convert "
    "files between supported formats; debug implementation issues; run validation commands; and report changed files "
    "with evidence. Provide a precise objective, scope, relevant paths or skills, expected artifacts, validation "
    "commands, and stopping condition. Do not use for table data retrieval, business analytics over source systems, "
    "or `load_data` calls; "
)


def build_coding_subagent_spec(
    *,
    model: Any,
    tools: list[Any],
    common_middleware: list[Any],
    skill_sources: list[str],
) -> dict[str, Any]:
    """Собирает параметры создания subagent для ограниченной работы с кодом.

    Args:
        model: Chat-модель LangChain для выполнения coding-задачи.
        tools: Дополнительные инструменты coding-agent.
        common_middleware: Middleware с управлением доступом к workspace tools.
        skill_sources: Виртуальные каталоги skills для нативного ``SkillsMiddleware``.

    Returns:
        Словарь именованных аргументов, совместимый с ``create_deep_agent``.
    """

    return {
        "name": CODING_AGENT_NAME,
        "system_prompt": CODING_AGENT_PROMPT,
        "model": model,
        "tools": list(tools),
        "skills": list(skill_sources),
        "middleware": list(common_middleware),
    }
