"""Интеграции DeepAgent с внешними сервисами.

Содержит:
- load_mcp_tools_safely: мягкая загрузка LangChain tools из MCP-сервиса.
"""

from deep_agent.integrations.mcp import load_mcp_tools_safely

__all__ = ["load_mcp_tools_safely"]
