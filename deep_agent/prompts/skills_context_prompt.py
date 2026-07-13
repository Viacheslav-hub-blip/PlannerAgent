"""Prompt-шаблоны контекста domain skills.

Содержит шаблоны предзагрузки skills для supervisor и data-agent.
"""

from __future__ import annotations

SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Предварительно загруженные skills
Middleware выбрал и полностью загрузил skills, которые выглядят релевантными запросу пользователя.
Их содержание ниже. Считай эти skills предметными инструкциями с более высоким приоритетом, чем базовый prompt.

{context}"""

DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Предварительно загруженные skills

Supervisor выбрал и загрузил следующие предметные skills для задачи чтения данных.

Считай их предметными инструкциями с более высоким приоритетом, чем базовый prompt. Не загружай их повторно.

{context}"""
