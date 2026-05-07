"""Optional LangChain adapters for the portable Hermes-inspired modules."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, List


def _load_structured_tool():
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "LangChain adapter requires 'langchain-core' (or LangChain) to be installed."
        ) from exc
    return StructuredTool


def build_memory_tools(memory_store: Any) -> List[Any]:
    """Return LangChain StructuredTool wrappers for the memory store."""

    StructuredTool = _load_structured_tool()

    def memory_add(target: str, content: str) -> dict:
        return memory_store.add(target, content)

    def memory_replace(target: str, old_text: str, new_content: str) -> dict:
        return memory_store.replace(target, old_text, new_content)

    def memory_remove(target: str, old_text: str) -> dict:
        return memory_store.remove(target, old_text)

    def memory_read(target: str) -> dict:
        return memory_store.read(target)

    return [
        StructuredTool.from_function(
            memory_add,
            name="memory_add",
            description="Add a durable memory entry to the memory or user store.",
        ),
        StructuredTool.from_function(
            memory_replace,
            name="memory_replace",
            description="Replace an existing memory entry using a unique substring match.",
        ),
        StructuredTool.from_function(
            memory_remove,
            name="memory_remove",
            description="Remove a memory entry using a unique substring match.",
        ),
        StructuredTool.from_function(
            memory_read,
            name="memory_read",
            description="Read the live state of the memory or user store.",
        ),
    ]


def build_skill_tools(skills_store: Any) -> List[Any]:
    """Return LangChain StructuredTool wrappers for the skills store."""

    StructuredTool = _load_structured_tool()

    def skills_list() -> list:
        return [asdict(skill) for skill in skills_store.list_skills()]

    def skill_view(name: str, file_path: str | None = None) -> dict:
        return skills_store.view_skill(name, file_path)

    def skill_create(name: str, content: str, category: str | None = None) -> dict:
        return skills_store.create_skill(name, content, category)

    def skill_patch(
        name: str,
        old_string: str,
        new_string: str,
        file_path: str | None = None,
        replace_all: bool = False,
    ) -> dict:
        return skills_store.patch_skill(
            name,
            old_string,
            new_string,
            file_path=file_path,
            replace_all=replace_all,
        )

    return [
        StructuredTool.from_function(
            skills_list,
            name="skills_list",
            description="List skill metadata only (progressive disclosure tier 1).",
        ),
        StructuredTool.from_function(
            skill_view,
            name="skill_view",
            description="Load the full contents of a skill or one linked file.",
        ),
        StructuredTool.from_function(
            skill_create,
            name="skill_create",
            description="Create a new skill with full YAML frontmatter plus markdown body.",
        ),
        StructuredTool.from_function(
            skill_patch,
            name="skill_patch",
            description="Patch an existing skill using Hermes-style fuzzy matching.",
        ),
    ]
