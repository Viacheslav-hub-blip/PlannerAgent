"""Декларативные capabilities аналитического coding-agent.

Содержит:
- CODE_WORKSPACE_TOOL_NAMES: стандартные инструменты workspace.
- BASE_SUPERVISOR_TOOL_NAMES: базовый набор tools supervisor без динамического гейтинга.
- GENERAL_PURPOSE_BASE_TOOL_NAMES: полный набор tools general-purpose subagent без ``load_data``.
"""

from __future__ import annotations

CODE_WORKSPACE_TOOL_NAMES = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"}
)
BASE_SUPERVISOR_TOOL_NAMES = frozenset(
    {"task", "execute_python_code", "load_skills", "write_todos", *CODE_WORKSPACE_TOOL_NAMES}
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


__all__ = [
    "BASE_SUPERVISOR_TOOL_NAMES",
    "CODE_WORKSPACE_TOOL_NAMES",
    "GENERAL_PURPOSE_BASE_TOOL_NAMES",
]
