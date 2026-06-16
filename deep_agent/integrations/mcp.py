"""Интеграция внешних MCP tools для DeepAgent.

Содержит:
- DEFAULT_MCP_TOOL_CONFIG: конфигурация MCP-сервиса по умолчанию.
- load_mcp_tools: асинхронная загрузка tools через MultiServerMCPClient.
- load_mcp_tools_safely: синхронная безопасная загрузка с soft-fail.
"""

from __future__ import annotations

import asyncio
from typing import Any

DEFAULT_MCP_TOOLS_URL = "http://127.0.0.1:8117/mcp"
DEFAULT_MCP_TOOL_CONFIG: dict[str, dict[str, str]] = {
    "graphics-tools": {
        "transport": "streamable_http",
        "url": DEFAULT_MCP_TOOLS_URL,
    }
}


async def load_mcp_tools(
    server_config: dict[str, Any] | None = None,
) -> list[Any]:
    """Асинхронно получает LangChain tools от MCP-сервиса.

    Args:
        server_config: Конфигурация серверов для ``MultiServerMCPClient``.

    Returns:
        Список LangChain tools, опубликованных MCP-сервисами.

    Raises:
        ConnectionError: MCP adapter не установлен или сервис недоступен.
    """

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise ConnectionError(
            "Для подключения MCP tools требуется пакет langchain-mcp-adapters."
        ) from exc

    client = MultiServerMCPClient(server_config or DEFAULT_MCP_TOOL_CONFIG)
    try:
        return list(await client.get_tools())
    except Exception as exc:
        raise ConnectionError(
            f"Не удалось получить инструменты от MCP-сервиса: {exc}"
        ) from exc


def load_mcp_tools_safely(
    server_config: dict[str, Any] | None = None,
) -> tuple[list[Any], str | None]:
    """Синхронно загружает MCP tools и мягко обрабатывает недоступность сервиса.

    Args:
        server_config: Конфигурация серверов для ``MultiServerMCPClient``.

    Returns:
        Пара ``(tools, error)``. При ошибке tools пустой, а error содержит
        понятное предупреждение для логов запуска.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    else:
        running_loop = True
    if running_loop:
        return [], "MCP tools отключены: синхронная загрузка вызвана внутри активного event loop."

    try:
        return asyncio.run(load_mcp_tools(server_config)), None
    except Exception as exc:
        return [], f"MCP tools отключены: {exc}"


__all__ = [
    "DEFAULT_MCP_TOOL_CONFIG",
    "DEFAULT_MCP_TOOLS_URL",
    "load_mcp_tools",
    "load_mcp_tools_safely",
]
