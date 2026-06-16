"""Декларативные capabilities аналитического coding-agent.

Содержит:
- CODE_WORKSPACE_SKILL_PATH: workspace-путь skill режима работы с кодом.
- IMAGE_ANALYSIS_SKILL_PATH: workspace-путь skill анализа изображений.
- MCP_TOOLS_SKILL_PATH: workspace-путь skill внешних MCP tools.
- BASE_SUPERVISOR_TOOL_NAMES: инструменты supervisor, доступные всегда.
- CODE_WORKSPACE_TOOL_NAMES: инструменты workspace, доступные после загрузки skill.
- IMAGE_ANALYSIS_TOOL_NAMES: инструменты анализа изображений.
- DATA_RETRIEVAL_TOOL_NAMES: инструменты data-retrieval-agent.
- SUPERVISOR_SKILL_TOOL_GRANTS: выдача tools supervisor по загруженным skills.
- GENERAL_PURPOSE_BASE_TOOL_NAMES: полный набор tools general-purpose subagent без ``load_data``.
"""

from __future__ import annotations

CODE_WORKSPACE_SKILL_PATH = "/deep_agent/skills/code-workspace/SKILL.md"
IMAGE_ANALYSIS_SKILL_PATH = "/deep_agent/skills/image-analysis/SKILL.md"
MCP_TOOLS_SKILL_PATH = "/deep_agent/skills/mcp-tools/SKILL.md"

BASE_SUPERVISOR_TOOL_NAMES = frozenset(
    {"task", "execute_python_code", "load_skills", "write_todos"}
)
CODE_WORKSPACE_TOOL_NAMES = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"}
)
IMAGE_ANALYSIS_TOOL_NAMES = frozenset({"analyze_image"})
DATA_RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "load_data",
        "load_skills",
        "execute_python_code",
        "write_todos",
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
    IMAGE_ANALYSIS_SKILL_PATH: IMAGE_ANALYSIS_TOOL_NAMES,
}
__all__ = [
    "BASE_SUPERVISOR_TOOL_NAMES",
    "CODE_WORKSPACE_SKILL_PATH",
    "CODE_WORKSPACE_TOOL_NAMES",
    "DATA_RETRIEVAL_TOOL_NAMES",
    "GENERAL_PURPOSE_BASE_TOOL_NAMES",
    "IMAGE_ANALYSIS_SKILL_PATH",
    "IMAGE_ANALYSIS_TOOL_NAMES",
    "MCP_TOOLS_SKILL_PATH",
    "SUPERVISOR_SKILL_TOOL_GRANTS",
]
