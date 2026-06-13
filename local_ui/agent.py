"""LangGraph entrypoint локального UI для аналитического DeepAgent.

Содержит функции:
- build_ui_agent: сборка графа агента для локального Agent Server.
"""

from __future__ import annotations

from typing import Any

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.settings import load_deep_agent_settings
from model import model as run_model
from tests.support.fake_spark_data import build_fake_spark_data_tools

ARTIFACTS_VIRTUAL_DIR = "/artifacts/"


def build_ui_agent() -> Any:
    """Собирает DeepAgent, совместимый с локальным LangGraph Agent Server.

    Returns:
        Скомпилированный граф без пользовательского checkpointer. Persistence,
        threads и streaming предоставляет Agent Server.
    """

    settings = load_deep_agent_settings()
    data_tools = build_fake_spark_data_tools(query_parser_model=run_model)
    return build_analytics_deep_agent(
        model=run_model,
        settings=settings,
        data_tools=data_tools,
        checkpointer=None,
        state_artifacts_virtual_dir=ARTIFACTS_VIRTUAL_DIR,
    )


agent = build_ui_agent()
