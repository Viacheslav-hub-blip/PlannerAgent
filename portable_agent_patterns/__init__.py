"""Portable Hermes-inspired agent runtime patterns.

This package extracts the most reusable Hermes Agent techniques into
dependency-light modules that can be embedded in other agent stacks,
including LangChain and LangGraph projects.

Modules:
    tool_runtime: Registry-driven tool surface with availability gating.
    memory: Frozen-snapshot memory store plus pluggable memory providers.
    skills: Progressive-disclosure skills store and skill editing workflow.
    self_improvement: Background review loop and nudge counters.
    langchain: Optional LangChain adapters.
    langgraph: Optional LangGraph node helpers.
"""

from portable_agent_patterns.memory import (
    MemoryManager,
    MemoryProvider,
    MemoryStore,
    build_memory_context_block,
    sanitize_context,
)
from portable_agent_patterns.self_improvement import (
    BackgroundReviewer,
    ReviewAction,
    ReviewConfig,
    ReviewNudger,
)
from portable_agent_patterns.skills import SkillMetadata, SkillsStore
from portable_agent_patterns.tool_runtime import ToolDefinition, ToolRegistry

__all__ = [
    "BackgroundReviewer",
    "MemoryManager",
    "MemoryProvider",
    "MemoryStore",
    "ReviewAction",
    "ReviewConfig",
    "ReviewNudger",
    "SkillMetadata",
    "SkillsStore",
    "ToolDefinition",
    "ToolRegistry",
    "build_memory_context_block",
    "sanitize_context",
]
