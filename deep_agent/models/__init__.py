"""Провайдеры и адаптеры chat-моделей DeepAgent.

Содержит:
- DeepAgentsKitaiChatModel: публичный KitAI-адаптер для Python-конфигурации.
- build_kitai_model: ленивая сборка KitAI-модели из переменных окружения.
"""

from deep_agent.models.kitai import DeepAgentsKitaiChatModel, build_kitai_model

__all__ = ["DeepAgentsKitaiChatModel", "build_kitai_model"]
