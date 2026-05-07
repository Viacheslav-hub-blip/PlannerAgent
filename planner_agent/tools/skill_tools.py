"""Инструменты чтения skills для runtime-агентов.

Содержит:
- build_skill_read_tools: создание LangChain tools для списка и загрузки skills.
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import BaseTool, tool

from ..services.skills_service import SkillsService


def build_skill_read_tools(skills_service: SkillsService | None) -> list[BaseTool]:
    """Создает инструменты чтения skills для planner/worker контекста.

    Args:
        skills_service: Сервис skills, из которого нужно читать список и полное
            содержимое навыков. Если сервис не передан, инструменты не создаются.

    Returns:
        Список LangChain tools: ``skill_list`` и ``skill_view``.
    """

    if skills_service is None:
        return []

    @tool("skill_list")
    def skill_list() -> str:
        """Показать список доступных skills с краткими описаниями."""

        records = [
            record.model_dump(mode="json")
            for record in skills_service.skills_list()
        ]
        return json.dumps(
            {"success": True, "skills": records},
            ensure_ascii=False,
            indent=2,
        )

    @tool("skill_view")
    def skill_view(name: str, file_path: Optional[str] = None) -> str:
        """Загрузить полный текст skill или связанный файл skill по имени."""

        result = skills_service.skill_view(name=name, file_path=file_path)
        return json.dumps(result, ensure_ascii=False, indent=2)

    return [skill_list, skill_view]


__all__ = ["build_skill_read_tools"]
