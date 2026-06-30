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
    "Маршрутизируй сюда ограниченные задачи с кодом и файлами workspace: изучить репозиторий, рефакторить "
    "существующий код, редактировать или создавать исходные файлы, тесты, prompts, skills, документацию, "
    "конфигурацию, notebooks и другие текстовые артефакты; конвертировать файлы между поддерживаемыми форматами; "
    "отлаживать проблемы реализации; запускать проверочные команды; возвращать измененные файлы с доказательствами. "
    "Агент обязан изучить релевантный локальный контекст, сам внести изменения в файлы, проверить их и вернуть "
    "доказательства вместо предложений, когда редактирование разрешено. Передавай точную цель, границы задачи, "
    "релевантные пути или skills, ожидаемые артефакты, команды проверки и условие остановки. Не используй для "
    "чтения табличных данных, бизнес-аналитики поверх source systems или вызовов `load_data`; "
)

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"
DATA_RETRIEVAL_AGENT_DESCRIPTION = (
    "Используй только для ограниченного чтения табличных данных через `load_data`. Подходящие задачи: проверить "
    "подтвержденные поля таблицы, выгрузить строки для известного источника/периода/фильтра, получить уникальные "
    "значения одной колонки для последующей смысловой классификации, найти строки по точным идентификаторам или "
    "точным кандидатным значениям и вернуть проверяемые доказательства: источник, поля, период, фильтры, число "
    "строк, preview/offload artifact и ограничения. Передавай точную цель выгрузки, источник или путь skill, "
    "нужные поля, точный период если он известен, подтвержденные фильтры, ожидаемые доказательства и условие "
    "остановки. Не используй для расчетов, агрегаций, группировок, join после выгрузки, смысловой классификации, "
    "преобразований dataframe, построения графиков/отчетов, экспортов или сохранения пользовательских артефактов; "
    "такие следующие шаги делегируй coding-agent."
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
