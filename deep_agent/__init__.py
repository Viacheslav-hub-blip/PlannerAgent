"""Гибридный LangChain DeepAgent для аналитики данных и работы с кодом.

Содержит:
- build_agent: единая сборка агента.
- AgentSettings: Python-настройки агента.
- load_agent_settings: создание настроек из defaults.
- build_gigachat_kitai_model: сборка Gigachat KitAI модели.
"""

from deep_agent.agent import build_agent
from deep_agent.agent_settings import AgentSettings, load_agent_settings
from deep_agent.gigachat_kitai_model import build_gigachat_kitai_model

__all__ = [
    "AgentSettings",
    "build_agent",
    "build_gigachat_kitai_model",
    "load_agent_settings",
]
