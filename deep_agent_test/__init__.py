"""Пакет аналитического native coding-agent.

Содержит:
- build_analytics_deep_agent: сборка аналитического DeepAgent.
- build_conversation_checkpointer: создание памяти текущего диалога.
- build_spark_data_tools: сборка инструмента чтения данных из Spark.
- load_deep_agent_settings: загрузка настроек агента из JSON-конфига.
"""

from deep_agent_test.core.analytics_deep_agent import (
    build_analytics_deep_agent,
    build_conversation_checkpointer,
)
from deep_agent_test.core.settings import load_deep_agent_settings
from deep_agent_test.tools.spark_data import build_spark_data_tools

__all__ = [
    "build_analytics_deep_agent",
    "build_conversation_checkpointer",
    "build_spark_data_tools",
    "load_deep_agent_settings",
]
