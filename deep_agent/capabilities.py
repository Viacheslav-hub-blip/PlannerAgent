"""Декларативные capabilities аналитического coding-agent.

Содержит:
- CODE_WORKSPACE_SKILL_PATH: workspace-путь skill режима работы с кодом.
- BASE_SUPERVISOR_TOOL_NAMES: инструменты supervisor, доступные всегда.
- CODE_WORKSPACE_TOOL_NAMES: инструменты workspace, доступные после загрузки skill.
- DATA_RETRIEVAL_TOOL_NAMES: инструменты data-retrieval-agent.
- SUPERVISOR_SKILL_TOOL_GRANTS: выдача tools supervisor по загруженным skills.
- GENERAL_PURPOSE_BASE_TOOL_NAMES: полный набор tools general-purpose subagent без ``load_data``.
"""

from __future__ import annotations

CODE_WORKSPACE_SKILL_PATH = "/deep_agent/skills/code-workspace/SKILL.md"

BASE_SUPERVISOR_TOOL_NAMES = frozenset(
    {"task", "execute_python_code", "load_skills", "write_todos"}
)
CODE_WORKSPACE_TOOL_NAMES = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"}
)
DATA_RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "load_data",
        "load_skills",
        "execute_python_code",
        "ls",
        "read_file",
        "glob",
        "grep",
    }
)
GENERAL_PURPOSE_BASE_TOOL_NAMES = frozenset(
    {
        "task",
        "write_todos",
        "execute_python_code",
        "load_skills",
        *CODE_WORKSPACE_TOOL_NAMES,
    }
)

SUPERVISOR_SKILL_TOOL_GRANTS = {
    CODE_WORKSPACE_SKILL_PATH: CODE_WORKSPACE_TOOL_NAMES,
}
__all__ = [
    "BASE_SUPERVISOR_TOOL_NAMES",
    "CODE_WORKSPACE_SKILL_PATH",
    "CODE_WORKSPACE_TOOL_NAMES",
    "DATA_RETRIEVAL_TOOL_NAMES",
    "GENERAL_PURPOSE_BASE_TOOL_NAMES",
    "SUPERVISOR_SKILL_TOOL_GRANTS",
]
