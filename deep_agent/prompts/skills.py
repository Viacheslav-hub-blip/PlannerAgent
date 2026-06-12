"""Prompt-шаблоны контекста domain skills.

Содержит шаблоны предзагрузки skills и компактного Skills Index.
"""

from __future__ import annotations

PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """
## Предварительно загруженные навыки

Эксперт выбрал и загрузил навыки, которые выглядят релевантными для запроса пользователя.

Их содержание приведено ниже. Относитесь к этим навыкам как к руководству по предметной области с более высоким приоритетом, чем базовый промпт. Не загружайте те же навыки повторно. Если требуемый навык отсутствует или неполон, загрузите недостающие навыки одним вызовом `load_skills(skill_names=..., already_loaded=...)`.

Используйте прогрессивное раскрытие: загруженные файлы `SKILL.md` дают контекст маршрутизации и рабочего процесса. Читайте дополнительные файлы, такие как `fields.md` или `joins.md`, только когда загруженный навык явно указывает на них и текущей задаче требуется эта деталь.

{context}
"""

SUPERVISOR_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Preloaded Skills

The middleware selected and fully loaded skills that appear relevant to the user request.

Their content is below. Treat these skills as domain guidance with higher priority than the base prompt. Do not load
the same skills again.

The supervisor cannot call `load_data`. If table data is needed, delegate it to `data-retrieval-agent`.
Filesystem and terminal tools are available only when the loaded skills grant them. If `code-workspace` is loaded,
use those tools for workspace code tasks. Use `load_skills` only for another verified `SKILL.md` path from the
Skills Index.

{context}"""

DATA_RETRIEVAL_PRELOADED_SKILLS_CONTEXT_PROMPT_TEMPLATE = """## Preloaded Skills

The supervisor selected and loaded the following domain skills for this retrieval task.

Treat them as domain guidance with higher priority than the base prompt. If required domain guidance is missing, call
`load_skills` only for an exact skill name or path known from verified context. Do not reload preloaded skills.
Read auxiliary files such as `fields.md` or `joins.md` with `grep` or `read_file` only when a loaded skill points to
them and the delegated task needs that detail.

{context}"""

SKILLS_INDEX_CONTEXT_PROMPT_TEMPLATE = """## Skills Index

Below is the index of skills that were not included in the Preloaded Skills block. Each item contains:
- `path`: virtual path to `SKILL.md` under `/skills/`;
- `name`: skill name;
- `description`: when the skill should be used.

Use this index only to decide whether additional skills are needed. If a required skill appears here, load it in one
`load_skills(skill_names=..., already_loaded=...)` call.

{skills_index}"""
