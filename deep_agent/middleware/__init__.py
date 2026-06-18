"""LangChain middleware для управления контекстом, логами и артефактами.

Содержит:
- ToolContextNoticeMiddleware: добавление понятных уведомлений к результатам tools.
"""

from deep_agent.middleware.tool_context_notice import ToolContextNoticeMiddleware

__all__ = ["ToolContextNoticeMiddleware"]
