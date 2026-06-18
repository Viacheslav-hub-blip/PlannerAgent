"""Tool получения внутренней структуры DeepAgent.

Содержит:
- GET_PROJECT_STRUCTURE_TOOL_NAME: имя инструмента структуры проекта.
- GET_PROJECT_STRUCTURE_DESCRIPTION: описание инструмента для модели.
- GetProjectStructureInput: схема аргументов инструмента ``get_project_structure``.
- GetProjectStructureTool: LangChain tool для возврата структуры проекта.
- build_get_project_structure_tool: фабрика инструмента структуры проекта.
- build_project_structure_report: сборка текстового отчета о внутренней структуре агента.
- _iter_agent_structure_lines: построение дерева файлов агента.
- _iter_tree_lines: рекурсивный обход дерева проекта.
- _should_skip_path: фильтрация служебных файлов дерева.
- _tree_entry_sort_key: стабильная сортировка дерева.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.settings import workspace_tool_path

GET_PROJECT_STRUCTURE_TOOL_NAME = "get_project_structure"
GET_PROJECT_STRUCTURE_DESCRIPTION = """
get_project_structure
---
Возвращает краткую карту внутренних файлов DeepAgent и путь к папке skills.
Используй tool, когда нужно понять расположение модулей агента или найти папку skills.
Tool не возвращает корневые документы, tests, scripts и содержимое отдельных skills.

Аргументы:
- `max_entries`: максимум строк дерева файлов.
""".strip()

AGENT_STRUCTURE_TARGETS = (
    "deep_agent",
)
SKIPPED_TREE_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".idea",
        ".langgraph_api",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "skills",
    }
)
SKIPPED_TREE_SUFFIXES = (".pyc", ".pyo")


class GetProjectStructureInput(BaseModel):
    """Аргументы tool ``get_project_structure``.

    Attributes:
        max_entries: Максимальное число строк дерева файлов в ответе.
    """

    max_entries: int = Field(
        default=450,
        ge=1,
        description="Максимальное число строк дерева файлов в ответе.",
    )


class GetProjectStructureTool(BaseTool):
    """LangChain tool получения структуры проекта.

    Args:
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        Tool, который возвращает markdown-отчет со структурой проекта.
    """

    name: str = GET_PROJECT_STRUCTURE_TOOL_NAME
    description: str = GET_PROJECT_STRUCTURE_DESCRIPTION
    args_schema: type[BaseModel] = GetProjectStructureInput

    _workspace_root: Path = PrivateAttr()

    def __init__(self, *, workspace_root: Path) -> None:
        """Создает tool поверх фактического workspace текущего запуска.

        Args:
            workspace_root: Фактический корень workspace.
        """

        super().__init__()
        self._workspace_root = workspace_root.resolve()

    def _run(
        self,
        max_entries: int = 450,
        **_: Any,
    ) -> str:
        """Синхронно возвращает структуру проекта.

        Args:
            max_entries: Максимальное число строк дерева файлов.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            Markdown-отчет со структурой проекта.
        """

        return build_project_structure_report(
            workspace_root=self._workspace_root,
            max_tree_entries=max(1, int(max_entries)),
        )

    async def _arun(
        self,
        max_entries: int = 450,
        **_: Any,
    ) -> str:
        """Асинхронная обёртка над :meth:`_run`.

        Args:
            max_entries: Максимальное число строк дерева файлов.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            Markdown-отчет со структурой проекта.
        """

        return self._run(max_entries=max_entries)


def build_get_project_structure_tool(
    *,
    workspace_root: Path,
) -> GetProjectStructureTool:
    """Собирает tool ``get_project_structure``.

    Args:
        workspace_root: Фактический корень workspace текущего запуска.

    Returns:
        Готовый ``GetProjectStructureTool``.
    """

    return GetProjectStructureTool(
        workspace_root=workspace_root,
    )


def build_project_structure_report(
    *,
    workspace_root: Path,
    max_tree_entries: int = 450,
) -> str:
    """Собирает текстовый отчет о внутренней структуре агента.

    Args:
        workspace_root: Корень workspace, от которого строятся workspace-пути.
        max_tree_entries: Максимальное число строк дерева файлов.

    Returns:
        Markdown-отчет с внутренними файлами агента и путем к папке skills.
    """

    workspace_path = workspace_tool_path(workspace_root, workspace_root, directory=True)
    agent_path = workspace_root / "deep_agent"
    skills_path = agent_path / "skills"
    tree_lines = _iter_agent_structure_lines(
        workspace_root=workspace_root,
        max_entries=max_tree_entries,
    )
    return "\n".join(
        [
            "# Agent Structure",
            "",
            f"- Workspace root: `{workspace_path}`",
            f"- Agent internals: `{workspace_tool_path(agent_path, workspace_root, directory=True)}`",
            f"- Skills directory: `{workspace_tool_path(skills_path, workspace_root, directory=True)}`",
            f"- Max tree entries: `{max_tree_entries}`",
            "",
            "## Internal Files",
            "",
            "```text",
            *tree_lines,
            "```",
        ]
    )


def _iter_agent_structure_lines(
    *,
    workspace_root: Path,
    max_entries: int,
) -> list[str]:
    """Строит компактное дерево файлов проекта.

    Args:
        workspace_root: Корень workspace.
        max_entries: Максимальное число строк дерева.

    Returns:
        Список строк для блока ``text``.
    """

    lines = [workspace_tool_path(workspace_root, workspace_root, directory=True)]
    for target_name in AGENT_STRUCTURE_TARGETS:
        target_path = workspace_root / target_name
        if not target_path.exists():
            continue
        lines.extend(
            _iter_tree_lines(
                target_path,
                workspace_root=workspace_root,
                indent="  ",
            )
        )
        if len(lines) >= max_entries:
            lines = lines[:max_entries]
            lines.append("  ...")
            break
    return lines


def _iter_tree_lines(
    path: Path,
    *,
    workspace_root: Path,
    indent: str,
) -> list[str]:
    """Рекурсивно строит строки дерева для файла или каталога.

    Args:
        path: Файл или каталог внутри workspace.
        workspace_root: Корень workspace для проверки границ.
        indent: Текущий отступ дерева.

    Returns:
        Список строк дерева.
    """

    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return []
    name = f"{path.name}/" if path.is_dir() else path.name
    lines = [f"{indent}{name}"]
    if not path.is_dir():
        return lines
    children = [
        child
        for child in path.iterdir()
        if not _should_skip_path(child)
    ]
    for child in sorted(children, key=_tree_entry_sort_key):
        lines.extend(
            _iter_tree_lines(
                child,
                workspace_root=workspace_root,
                indent=f"{indent}  ",
            )
        )
    return lines


def _should_skip_path(path: Path) -> bool:
    """Проверяет, нужно ли скрыть служебный файл из дерева.

    Args:
        path: Проверяемый путь.

    Returns:
        ``True``, если файл или каталог не должен попадать в отчет.
    """

    return path.name in SKIPPED_TREE_NAMES or path.suffix in SKIPPED_TREE_SUFFIXES


def _tree_entry_sort_key(path: Path) -> tuple[int, str]:
    """Возвращает ключ сортировки дерева.

    Args:
        path: Файл или каталог.

    Returns:
        Кортеж для стабильной сортировки: каталоги перед файлами, затем имя.
    """

    return (0 if path.is_dir() else 1, path.name.lower())


__all__ = [
    "GET_PROJECT_STRUCTURE_DESCRIPTION",
    "GET_PROJECT_STRUCTURE_TOOL_NAME",
    "GetProjectStructureInput",
    "GetProjectStructureTool",
    "build_project_structure_report",
    "build_get_project_structure_tool",
]
