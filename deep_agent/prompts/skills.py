"""Prompt-шаблоны контекста domain skills.

Содержит шаблоны предзагрузки skills и компактного Skills Index.
"""

from __future__ import annotations

PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """
## Предварительно загруженные навыки

Эксперт выбрал и загрузил навыки, которые выглядят релевантными для запроса пользователя.

Их содержание приведено ниже. Относитесь к этим навыкам как к руководству по предметной области с более высоким приоритетом, чем базовый промпт. Не загружайте те же навыки повторно.

Используйте содержание навыков как контекст предметной области и рабочего процесса.

{context}
"""

SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Preloaded Skills

The middleware selected and fully loaded skills that appear relevant to the user request.

Their content is below. Treat these skills as domain guidance with higher priority than the base prompt. Do not load
the same skills again.

{context}"""

DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Preloaded Skills

The supervisor selected and loaded the following domain skills for this retrieval task.

Treat them as domain guidance with higher priority than the base prompt. Do not reload preloaded skills.

{context}"""

SKILLS_INDEX_CONTEXT_PROMPT_TEMPLATE = """## Skills Index

Below is the index of skills that were not included in the Preloaded Skills block. Each item contains:
- `path`: workspace path to `SKILL.md` under `/deep_agent/skills/`;
- `name`: skill name;
- `description`: when the skill should be used.

Use this index only to decide whether additional domain guidance is needed.

{skills_index}"""
