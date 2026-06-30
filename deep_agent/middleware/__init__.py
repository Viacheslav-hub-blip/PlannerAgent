"""LangChain middleware для управления контекстом tools и артефактами.

Содержит:
- ToolContextNoticeMiddleware: добавление понятных уведомлений к результатам tools.
"""

from deep_agent.middleware.tool_context_middleware import ToolContextNoticeMiddleware

__all__ = ["ToolContextNoticeMiddleware"]
