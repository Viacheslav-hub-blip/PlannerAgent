"""Спецификация coding-subagent.

Содержит функцию:
- build_coding_subagent_spec: сборка параметров создания coding-agent.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.coding import CODING_AGENT_PROMPT

CODING_AGENT_NAME = "coding-agent"
CODING_AGENT_DESCRIPTION = (
    "Маршрутизируй сюда ограниченные задачи с кодом и файлами workspace: изучить репозиторий, рефакторить "
    "существующий код, редактировать или создавать source files, tests, prompts, skills, documentation, "
    "configuration, notebooks и другие text artifacts; конвертировать files между поддерживаемыми форматами; "
    "отлаживать implementation issues; запускать validation commands; возвращать changed files with evidence. "
    "Агент обязан изучить relevant local context, сам внести file changes, validate them и report evidence вместо "
    "suggestions, когда editing allowed. Передавай precise objective, scope, relevant paths or skills, expected "
    "artifacts, validation commands и stopping condition. Не используй для table data retrieval, business analytics "
    "over source systems или `load_data` calls; "
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
