"""Конфигурация специализированных подагентов DeepAgent.

Содержит:
- CODING_AGENT_NAME: имя подагента для задач разработки.
- CODING_AGENT_DESCRIPTION: описание маршрутизации задач разработки.
- DATA_RETRIEVAL_AGENT_NAME: имя подагента для чтения табличных данных.
- DATA_RETRIEVAL_AGENT_DESCRIPTION: описание маршрутизации задач чтения данных.
"""

from __future__ import annotations

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

__all__ = [
    "CODING_AGENT_DESCRIPTION",
    "CODING_AGENT_NAME",
    "DATA_RETRIEVAL_AGENT_DESCRIPTION",
    "DATA_RETRIEVAL_AGENT_NAME",
]
