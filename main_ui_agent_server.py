"""Запуск UI API вместе с ResearchAgent и инструментами генерации кода.

Содержит:
- _load_code_generator_tools: загрузка MCP tools генерации кода.
- _build_sandbox: создание пустой Python-песочницы с разрешенными библиотеками.
- _build_agent_with_code_tools: сборка ResearchAgent с sandbox и tools.
- _run_async_before_server_start: синхронный запуск async-кода до старта uvicorn.
- create_app_with_agent: factory FastAPI приложения для `uvicorn --factory`.

Файл нужен для локального запуска analyst UI так, чтобы кнопка запуска анализа
работала через реальные endpoints `/api/v1/runs/invoke` и `/api/v1/branches/invoke`,
а worker мог вызывать MCP-инструмент `generate_python_code` на порту 8201.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from examples.fake_spark_tools import build_fake_spark_tools
from model import model as deepseek_model
from planner_agent import ResearchAgent
from sandbox import ClientPythonSandbox
from planner_agent.http_api import ApiSettings, create_app
from planner_agent.http_api.config import ApiServices


PROJECT_ROOT = Path(__file__).resolve().parent
EXAMPLE_ROOT = PROJECT_ROOT / "examples"
CODE_MCP_URL = "http://127.0.0.1:8201/mcp"


async def _load_code_generator_tools() -> list[BaseTool]:
    """Загружает LangChain tools из MCP-сервера генерации Python-кода.

    Args:
        Отсутствуют. URL MCP-сервера берется из константы `CODE_MCP_URL`.

    Returns:
        Список LangChain tools, опубликованных MCP-сервером на порту 8201.

    Raises:
        RuntimeError: Если MCP-сервер недоступен или не вернул tools.
    """

    client = MultiServerMCPClient(
        {
            "generate_python_code": {
                "transport": "streamable_http",
                "url": CODE_MCP_URL,
            }
        }
    )
    tools = await client.get_tools()
    if not tools:
        raise RuntimeError(f"MCP code generator server returned no tools: {CODE_MCP_URL}")
    return tools


def _build_sandbox() -> ClientPythonSandbox:
    """Создает Python-песочницу без предзагруженных пользовательских таблиц.

    Args:
        Отсутствуют.

    Returns:
        ClientPythonSandbox с доступными библиотеками `pd`, `px`.
    """

    return ClientPythonSandbox(allowed_libraries={"pd": pd, "px": px})


async def _build_agent_with_code_tools() -> ResearchAgent:
    """Собирает ResearchAgent для UI с fake Spark tools и MCP code-generator tool.

    Args:
        Отсутствуют.

    Returns:
        ResearchAgent, совместимый с LangChain Runnable API и подключенный к
        локальной Python-песочнице.
    """

    sandbox = _build_sandbox()
    code_tools = await _load_code_generator_tools()
    spark_tools = build_fake_spark_tools(
        delay_seconds=0.5,
        transaction_count=120,
        day_event_count=40,
    )
    tools = [*spark_tools, *code_tools]
    code_tool_names = {tool.name for tool in code_tools}

    return ResearchAgent(
        model=deepseek_model,
        sandbox=sandbox,
        tools=tools,
        code_generator_tool_names=code_tool_names,
        enable_workspace_tools=True,
        workspace_root=str(PROJECT_ROOT),
        sources_dir=str(EXAMPLE_ROOT / "data"),
        contexts_dir=str(PROJECT_ROOT / "skills"),
        skills_dir=str(PROJECT_ROOT / "skills"),
        memory_dir=str(EXAMPLE_ROOT / "memory"),
        runs_dir=str(EXAMPLE_ROOT / "runs"),
    )


def _run_async_before_server_start(coro: Any) -> Any:
    """Выполняет coroutine до запуска event loop FastAPI/uvicorn.

    Args:
        coro: Coroutine, которую нужно выполнить синхронно.

    Returns:
        Результат выполнения coroutine.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        """Запускает coroutine в отдельном потоке с отдельным event loop.

        Args:
            Отсутствуют. Использует coroutine из замыкания.

        Returns:
            None. Результат или ошибка сохраняются в словарь `result`.
        """

        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, name="research-agent-factory-loader")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def create_app_with_agent():
    """Создает FastAPI приложение с подключенным ResearchAgent.

    Args:
        Отсутствуют. Агент собирается из текущего проекта, `model.py`,
        fake Spark tools и MCP code-generator tool на `http://127.0.0.1:8201/mcp`.

    Returns:
        FastAPI приложение, которое раздает статический UI по `/app/` и умеет
        запускать агента через API endpoints.
    """

    agent = _run_async_before_server_start(_build_agent_with_code_tools())
    services = ApiServices(
        lineage_service=agent.lineage_service,
        artifact_service=agent.artifact_service,
        inspection_service=agent.inspection_service,
        dialog_context_service=agent.dialog_context_service,
        skills_service=agent.skills_service,
        agent=agent,
    )
    return create_app(
        settings=ApiSettings(
            workspace_root=str(PROJECT_ROOT),
            runs_dir=str(EXAMPLE_ROOT / "runs"),
            api_prefix="/api/v1",
        ),
        services=services,
    )
