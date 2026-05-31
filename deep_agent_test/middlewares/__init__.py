"""Middleware аналитического DeepAgent.

Содержит:
- PreloadedSkillsContextMiddleware: предзагрузка skills в prompt агентов.
- ToolOutputFileMiddleware: сохранение больших табличных результатов в pickle.
- ToolLoopGuardMiddleware: защита от повторяющихся tool-вызовов.
- CriticLoopCapMiddleware: ограничение числа проверок внутреннего critic-а.
"""

from deep_agent_test.middlewares.critic_loop_cap import CriticLoopCapMiddleware
from deep_agent_test.middlewares.skills_context import PreloadedSkillsContextMiddleware
from deep_agent_test.middlewares.tool_loop_guard import ToolLoopGuardMiddleware
from deep_agent_test.middlewares.tool_output_file import ToolOutputFileMiddleware

__all__ = [
    "CriticLoopCapMiddleware",
    "PreloadedSkillsContextMiddleware",
    "ToolLoopGuardMiddleware",
    "ToolOutputFileMiddleware",
]
