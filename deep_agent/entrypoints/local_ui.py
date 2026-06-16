"""LangGraph entrypoint локального UI для аналитического DeepAgent.

Содержит функции:
- build_ui_agent: сборка графа агента для локального Agent Server.
- _build_ui_extra_tools: сборка необязательных VLM и MCP tools для UI.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.models.instances import build_local_ui_model
from deep_agent.settings import load_deep_agent_settings
from deep_agent.tools.image_analysis import build_analyze_image_tool
from deep_agent.integrations.mcp import load_mcp_tools_safely
from tests.support.fake_spark_data import build_fake_spark_data_tools

ARTIFACTS_VIRTUAL_DIR = "/artifacts/"


def build_ui_agent() -> Any:
    """Собирает DeepAgent, совместимый с локальным LangGraph Agent Server.

    Returns:
        Скомпилированный граф без пользовательского checkpointer. Persistence,
        threads и streaming предоставляет Agent Server.
    """

    settings = load_deep_agent_settings()
    run_model = build_local_ui_model()
    data_tools = build_fake_spark_data_tools(query_parser_model=run_model)
    return build_analytics_deep_agent(
        model=run_model,
        settings=settings,
        data_tools=data_tools,
        checkpointer=None,
        state_artifacts_virtual_dir=ARTIFACTS_VIRTUAL_DIR,
        extra_tools=_build_ui_extra_tools(settings.workspace_root),
    )


def _build_ui_extra_tools(workspace_root: str | Path) -> list[Any]:
    """Собирает дополнительные tools UI без падения при недоступном MCP.

    Returns:
        Список VLM и MCP tools. Если MCP-сервис недоступен, возвращаются только
        локально созданные tools, а причина пишется в warning.
    """

    tools: list[Any] = [build_analyze_image_tool(workspace_root=workspace_root)]
    mcp_tools, error = load_mcp_tools_safely()
    if error:
        warnings.warn(error, RuntimeWarning, stacklevel=2)
    tools.extend(mcp_tools)
    return tools


agent = build_ui_agent()
