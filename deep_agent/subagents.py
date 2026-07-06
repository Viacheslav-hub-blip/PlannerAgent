"""Конфигурация специализированных подагентов DeepAgent.

Содержит:
- CODING_AGENT_NAME: имя подагента для задач разработки.
- CODING_AGENT_DESCRIPTION: описание маршрутизации задач разработки.
- DATA_RETRIEVAL_AGENT_NAME: имя подагента для чтения табличных данных.
- DATA_RETRIEVAL_AGENT_DESCRIPTION: описание маршрутизации задач чтения данных.
- build_coding_subagent_config: сборка конфигурации coding-agent.
- build_data_retrieval_subagent_config: сборка конфигурации data-retrieval-agent.
- build_supervisor_subagent_configs: сборка списка подагентов для supervisor.
"""

from __future__ import annotations

from typing import Any

from deep_agent.prompts.coding_agent_prompt import CODING_AGENT_PROMPT
from deep_agent.prompts.data_retrieval_agent_prompt import DATA_RETRIEVAL_PROMPT

CODING_AGENT_NAME = "coding-agent"

CODING_AGENT_DESCRIPTION = (
    "Используй этого subagent (сотрудника) для крупных атомарных этапов, связанных с написанием кода "
    "(рефакторинг, написание скриптов, исполнение), аналитикой (работой с dataframe, подсчет метрик, "
    "расчеты и срезы), созданием файлов (перемещение, создание, редактирование), работой с jupyter файлами "
    "и проверкой результата. Не отправляй ему микрошаги без самостоятельного результата."
)

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"

DATA_RETRIEVAL_AGENT_DESCRIPTION = (
    "Используй этого subagent (сотрудника) для атомарных задач обращения к таблицам и базам данных "
    "(подтверждение источников, выгрузка данных, сохранение результата и отчет с filters/counts/artifact paths). "
    "Этот subagent занимается только загрузкой данных и сохранением в виде файла. Он не делает расчеты или срезы, только выгрузка."
)


def build_coding_subagent_config(
        *,
        model: Any,
        tools: list[Any],
        common_middleware: list[Any],
        skill_sources: list[str],
) -> dict[str, Any]:
    """Собирает конфигурацию подагента для ограниченной работы с кодом.

    Args:
        model: Chat-модель LangChain для выполнения coding-задачи.
        tools: Дополнительные инструменты coding-agent.
        common_middleware: Middleware с управлением доступом к workspace tools.
        skill_sources: Виртуальные каталоги skills для нативного ``SkillsMiddleware``.

    Returns:
        Словарь аргументов для ``create_deep_agent``.
    """

    return {
        "name": CODING_AGENT_NAME,
        "system_prompt": CODING_AGENT_PROMPT,
        "model": model,
        "tools": list(tools),
        "skills": list(skill_sources),
        "middleware": list(common_middleware),
    }


def build_data_retrieval_subagent_config(
        *,
        model: Any,
        data_tools: list[Any],
        common_middleware: list[Any],
        skill_sources: list[str],
) -> dict[str, Any]:
    """Собирает конфигурацию подагента для чтения табличных данных.

    Args:
        model: Chat-модель LangChain для выполнения запросов subagent.
        data_tools: Инструменты чтения и обработки данных.
        common_middleware: Middleware, подключаемые к subagent.
        skill_sources: Виртуальные каталоги skills для нативного ``SkillsMiddleware``.

    Returns:
        Словарь аргументов для ``create_deep_agent``.
    """

    return {
        "name": DATA_RETRIEVAL_AGENT_NAME,
        "system_prompt": DATA_RETRIEVAL_PROMPT,
        "model": model,
        "tools": list(data_tools),
        "skills": list(skill_sources),
        "middleware": list(common_middleware),
    }


def build_supervisor_subagent_configs(
        *,
        coding_agent: Any,
        data_retrieval_agent: Any,
) -> list[dict[str, Any]]:
    """Собирает список подагентов, доступных главному supervisor.

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


__all__ = [
    "CODING_AGENT_DESCRIPTION",
    "CODING_AGENT_NAME",
    "DATA_RETRIEVAL_AGENT_DESCRIPTION",
    "DATA_RETRIEVAL_AGENT_NAME",
    "build_coding_subagent_config",
    "build_data_retrieval_subagent_config",
    "build_supervisor_subagent_configs",
]
