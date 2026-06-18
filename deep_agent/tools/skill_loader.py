"""Tool пакетной загрузки skills для supervisor и subagents.

Содержит:
- build_load_skills_tool: фабрика tool ``load_skills`` с замыканием на settings.
- _build_skill_lookup: индекс соответствий токен -> файл skill (path/name/folder).
- _resolve_token: разрешение одного токена запроса в запись skill.
- _split_tokens: разбор строкового списка вида ``skill1, skill2``.
- _build_report: сборка финального текстового отчёта tool с контентом skills.

Tool детерминированно конкатенирует контент выбранных ``SKILL.md`` с заголовком-именем
перед каждым skill, дедуплицирует уже загруженные skills (middleware preload, прошлые
вызовы load_skills и явный ``already_loaded``) и не отдаёт их контент в контекст агента
повторно.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from deep_agent.settings import DeepAgentSettings, workspace_tool_path
from deep_agent.middleware.skills_context import (
    _parse_skill_index_entry,
    _read_context_file,
    _workspace_skill_path,
    discover_skill_context_files,
    rewrite_workspace_skill_references,
)

LOAD_SKILLS_TOOL_NAME = "load_skills"
LOAD_SKILLS_MAX_CHARS = 12000

LOAD_SKILLS_DESCRIPTION = """
Loads selected skill content (`SKILL.md`) in one call.

Use when:
- a required skill is not present in the Preloaded Skills section;
- a loaded skill explicitly references another known skill path;
- the supervisor already knows the exact skill name or virtual path from verified context.

Do not use when:
- you need `fields.md`, `joins.md`, or another auxiliary file. `load_skills` loads only `SKILL.md` files from the
  Skills Index. Use filesystem tools for auxiliary files.

What it does:
- reads each requested `SKILL.md` and returns its verbatim content;
- prefixes every loaded skill with its name and workspace path;
- skips skills that were already loaded through middleware preload, previous `load_skills` calls, or `already_loaded`.

Arguments:
- `skill_names`: comma-separated known skill names or workspace paths in one string, for example
  `skill-a, skill-b` or
  `/home/user_123456/deep_agent/skills/skill-a/SKILL.md, /home/user_123456/deep_agent/skills/skill-b/SKILL.md`;
- `already_loaded`: comma-separated skills that should not be loaded again. This can be empty.

Use `load_skills` only for batch loading verified skills into the supervisor context. Do not guess names and do not
request every available skill. Do not pass paths like `/home/user_123456/deep_agent/skills/name/fields.md`; they are
not skills.
""".strip()


def _split_tokens(raw: str) -> list[str]:
    """Разбирает строковый список вида ``skill1, skill2`` в список токенов."""

    if not raw:
        return []
    return [token.strip() for token in str(raw).split(",") if token.strip()]


def _build_skill_lookup(
    settings: DeepAgentSettings,
    *,
    skills_root: Path | None = None,
    workspace_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Строит индекс соответствий токен (lower) -> запись skill.

    Один skill доступен по нескольким токенам: workspace-путь, относительный путь,
    имя папки и ``name`` из front matter.

    Args:
        settings: Настройки агента.
        skills_root: Фактическая папка skills текущего запуска.
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        Словарь поиска skill по имени, папке, относительному и workspace-пути.
    """

    resolved_skills_root = (skills_root or settings.skills_root).resolve()
    resolved_workspace_root = (workspace_root or settings.workspace_root).resolve()
    lookup: dict[str, dict[str, str]] = {}
    skills_workspace_dir = workspace_tool_path(
        resolved_skills_root,
        resolved_workspace_root,
        directory=True,
    )
    for local_path in discover_skill_context_files(resolved_skills_root):
        workspace_path = _workspace_skill_path(
            resolved_skills_root,
            local_path,
            skills_workspace_dir,
        )
        header = _read_context_file(local_path, max_chars=4000) or ""
        parsed = _parse_skill_index_entry(header)
        name = parsed.get("name") or local_path.parent.name
        try:
            relative_path = local_path.relative_to(resolved_skills_root).as_posix()
        except ValueError:
            relative_path = local_path.name
        entry = {
            "workspace_path": workspace_path,
            "local_path": str(local_path),
            "name": name,
        }
        for token in {workspace_path, relative_path, local_path.parent.name, name}:
            token = (token or "").strip().lower()
            if token:
                lookup.setdefault(token, entry)
    return lookup


def _resolve_token(token: str, lookup: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Разрешает один токен запроса в запись skill или ``None``, если не найден."""

    key = token.strip().lower()
    if key in lookup:
        return lookup[key]
    if not key.endswith("/skill.md"):
        with_file = f"{key.rstrip('/')}/skill.md"
        if with_file in lookup:
            return lookup[with_file]
    return None


def _build_report(
    blocks: list[str],
    newly_loaded: list[str],
    skipped: list[str],
    unknown: list[str],
) -> str:
    """Собирает финальный текстовый отчёт tool с контентом и заметками."""

    sections: list[str] = []
    if blocks:
        sections.append("## Загруженные skills\n\n" + "\n\n".join(blocks))
    else:
        sections.append("## Загруженные skills\n\nНовых skills не загружено.")

    notes: list[str] = []
    if skipped:
        notes.append("Пропущены как уже загруженные: " + ", ".join(skipped))
    if unknown:
        notes.append("Не найдены в Skills Index: " + ", ".join(unknown))
    if notes:
        sections.append("\n".join(notes))
    return "\n\n".join(sections)


def build_load_skills_tool(
    settings: DeepAgentSettings,
    *,
    skills_root: Path | None = None,
    workspace_root: Path | None = None,
) -> Any:
    """Собирает общий tool ``load_skills`` для агента с замыканием на settings.

    Args:
        settings: Настройки агента.
        skills_root: Фактическая папка skills текущего запуска.
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        LangChain tool ``load_skills``.
    """

    lookup = _build_skill_lookup(
        settings,
        skills_root=skills_root,
        workspace_root=workspace_root,
    )
    max_chars = LOAD_SKILLS_MAX_CHARS
    resolved_skills_root = (skills_root or settings.skills_root).resolve()
    resolved_workspace_root = (workspace_root or settings.workspace_root).resolve()
    skills_workspace_dir = workspace_tool_path(
        resolved_skills_root,
        resolved_workspace_root,
        directory=True,
    )

    @tool(LOAD_SKILLS_TOOL_NAME, description=LOAD_SKILLS_DESCRIPTION)
    def load_skills(
        skill_names: str,
        already_loaded: str = "",
        state: Annotated[dict, InjectedState] = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = "",
    ) -> Command:
        """Загружает skills по строковому списку имён/путей и дедуплицирует контекст.

        Args:
            skill_names: Имена или виртуальные пути skills через запятую.
            already_loaded: Уже загруженные skills через запятую, которые нужно пропустить.
        """

        state = state or {}
        requested = _split_tokens(skill_names)

        already_seen: set[str] = set()
        already_seen.update(state.get("preloaded_skill_paths") or [])
        already_seen.update(state.get("materialized_skill_paths") or [])
        for token in _split_tokens(already_loaded):
            entry = _resolve_token(token, lookup)
            already_seen.add(entry["workspace_path"] if entry else token)

        blocks: list[str] = []
        newly_loaded: list[str] = []
        skipped: list[str] = []
        unknown: list[str] = []
        for token in requested:
            entry = _resolve_token(token, lookup)
            if entry is None:
                unknown.append(token)
                continue
            workspace_path = entry["workspace_path"]
            if workspace_path in already_seen:
                skipped.append(workspace_path)
                continue
            content = _read_context_file(Path(entry["local_path"]), max_chars)
            if content is None:
                unknown.append(token)
                continue
            content = rewrite_workspace_skill_references(content, skills_workspace_dir)
            already_seen.add(workspace_path)
            newly_loaded.append(workspace_path)
            blocks.append(f"### {entry['name']} ({workspace_path})\n\n{content}")

        report = _build_report(blocks, newly_loaded, skipped, unknown)
        materialized = [*(state.get("materialized_skill_paths") or []), *newly_loaded]
        return Command(
            update={
                "materialized_skill_paths": materialized,
                "messages": [
                    ToolMessage(report, tool_call_id=tool_call_id, name=LOAD_SKILLS_TOOL_NAME)
                ],
            }
        )

    return load_skills


__all__ = [
    "LOAD_SKILLS_DESCRIPTION",
    "LOAD_SKILLS_MAX_CHARS",
    "LOAD_SKILLS_TOOL_NAME",
    "build_load_skills_tool",
]
