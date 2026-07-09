"""Инструмент обновления файловой памяти профиля пользователя.

Содержит:
- SaveUserFactInput: схема аргументов инструмента сохранения факта.
- build_save_user_fact_tool: создает tool сохранения факта пользователя.
- save_user_fact: добавляет новый факт в файл памяти профиля.
- _normalize_fact: нормализует текст факта.
- _ensure_facts_section: гарантирует наличие секции фактов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from deep_agent.memory.user_profile_memory import UserProfileMemory


class SaveUserFactInput(BaseModel):
    """Аргументы инструмента сохранения факта о пользователе.

    Args:
        fact: Короткий устойчивый факт, предпочтение или важный контекст о пользователе.

    Returns:
        Валидированные аргументы инструмента.
    """

    fact: str = Field(
        ...,
        description="Короткий устойчивый факт, предпочтение или важный контекст о пользователе.",
    )


def build_save_user_fact_tool(profile: UserProfileMemory) -> StructuredTool:
    """Создает tool для добавления новых фактов в файл памяти профиля.

    Args:
        profile: Ссылка на файловую память профиля пользователя.

    Returns:
        LangChain ``StructuredTool`` для сохранения фактов пользователя.
    """

    def _save_user_fact(fact: str) -> str:
        """Сохраняет факт о пользователе в привязанный файл памяти.

        Args:
            fact: Короткий устойчивый факт, предпочтение или важный контекст.

        Returns:
            Текстовый результат выполнения инструмента.
        """

        return save_user_fact(profile.file_path, fact)

    return StructuredTool.from_function(
        func=_save_user_fact,
        name="save_user_fact",
        description=(
            "Сохраняет новый устойчивый факт, предпочтение или важный контекст "
            "о текущем пользователе в его файл памяти."
        ),
        args_schema=SaveUserFactInput,
    )


def save_user_fact(memory_file: str | Path, fact: str) -> str:
    """Добавляет новый факт в секцию ``## Facts`` файла памяти профиля.

    Args:
        memory_file: Физический путь к файлу памяти профиля пользователя.
        fact: Короткий устойчивый факт, предпочтение или важный контекст.

    Returns:
        Сообщение о результате сохранения.
    """

    normalized_fact = _normalize_fact(fact)
    if not normalized_fact:
        return "Факт не сохранен: пустой текст."

    path = Path(memory_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8") if path.exists() else "# User profile\n"
    content = _ensure_facts_section(content)
    fact_line = f"- {normalized_fact}"
    if fact_line in content.splitlines():
        return "Факт уже есть в памяти пользователя."

    updated_content = content.rstrip() + f"\n{fact_line}\n"
    path.write_text(updated_content, encoding="utf-8")
    return "Факт сохранен в памяти пользователя."


def _normalize_fact(fact: Any) -> str:
    """Нормализует текст факта перед записью в память.

    Args:
        fact: Исходное значение факта.

    Returns:
        Очищенный однострочный текст факта без маркера списка.
    """

    normalized = " ".join(str(fact).strip().split())
    return normalized.removeprefix("-").strip()


def _ensure_facts_section(content: str) -> str:
    """Гарантирует наличие секции ``## Facts`` в markdown-файле памяти.

    Args:
        content: Текущее содержимое файла памяти.

    Returns:
        Содержимое файла с секцией фактов.
    """

    if "## Facts" in content:
        return content
    return content.rstrip() + "\n\n## Facts\n"
