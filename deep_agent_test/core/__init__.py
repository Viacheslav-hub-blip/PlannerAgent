"""Ядро аналитического coding-agent.

Содержит:
- build_analytics_deep_agent: сборка supervisor и subagents.
- build_conversation_checkpointer: создание памяти текущего диалога.
- build_data_tools: сборка data-tools из фабрики в настройках.
- load_deep_agent_settings: загрузка настроек агента.
"""

from deep_agent_test.core.analytics_deep_agent import (
    build_analytics_deep_agent,
    build_conversation_checkpointer,
    build_data_tools,
)
from deep_agent_test.core.settings import load_deep_agent_settings

__all__ = [
    "build_analytics_deep_agent",
    "build_conversation_checkpointer",
    "build_data_tools",
    "load_deep_agent_settings",
]
