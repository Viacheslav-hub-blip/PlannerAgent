"""Провайдеры и адаптеры chat-моделей DeepAgent.

Содержит:
- DeepAgentsKitaiChatModel: публичный KitAI-адаптер для Python-конфигурации.
- build_kitai_model: ленивая сборка KitAI-модели из переменных окружения.
- QwenVLMClient: клиент OpenAI-совместимой визуальной модели.
- QwenVLMConfig: конфигурация визуальной модели.
"""

from deep_agent.models.kitai import DeepAgentsKitaiChatModel, build_kitai_model
from deep_agent.models.vlm import QwenVLMClient, QwenVLMConfig

__all__ = [
    "DeepAgentsKitaiChatModel",
    "QwenVLMClient",
    "QwenVLMConfig",
    "build_kitai_model",
]
