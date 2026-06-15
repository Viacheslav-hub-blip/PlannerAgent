"""Провайдеры и адаптеры chat-моделей DeepAgent.

Содержит:
- build_kitai_model: ленивая сборка KitAI-модели из переменных окружения.
"""

from deep_agent.models.kitai import build_kitai_model

__all__ = ["build_kitai_model"]
