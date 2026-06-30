"""Adapter запуска DeepAgent через LangGraph Agent Server.

Содержит:
- KITAI_MODEL_CONFIG: явные параметры KitAI-модели для локального запуска.
- build_langgraph_agent_server_agent: сборка агента для LangGraph Agent Server.
- agent: экспортируемый граф, который читает ``local_ui/langgraph.json``.
"""

from __future__ import annotations

from typing import Any

from deep_agent.agent import build_agent
from deep_agent.agent_settings import load_agent_settings
from deep_agent.gigachat_kitai_model import build_gigachat_kitai_model

ARTIFACTS_VIRTUAL_DIR = "/artifacts/"
KITAI_MODEL_CONFIG = {
    "kitai_host_sdk": "",
    "cert_file": "",
    "key_file": "",
    "model": "GigaChat-2-Max",
    "verify_ssl": False,
    "system_name": "lab",
    "module_name": "lab_antifraud_edge",
    "polling_retries": 500,
    "polling_delay_in_sec": 2,
    "polling_start_delay_in_sec": 2,
    "polling_timeout_in_sec": 180,
    "temperature": 0.05,
    "profanity_check": False,
    "verbose": True,
}


def build_langgraph_agent_server_agent() -> Any:
    """Собирает DeepAgent для LangGraph Agent Server.

    Args:
        Отсутствуют. Adapter использует Python-настройки проекта и не подключает
        тестовые источники данных.

    Returns:
        Скомпилированный граф без пользовательского checkpointer. Persistence,
        threads и streaming предоставляет LangGraph Agent Server.
    """

    settings = load_agent_settings()
    model = build_gigachat_kitai_model(**KITAI_MODEL_CONFIG)
    return build_agent(
        model=model,
        settings=settings,
        data_tools=[],
        checkpointer=None,
        state_artifacts_virtual_dir=ARTIFACTS_VIRTUAL_DIR,
    )


agent = build_langgraph_agent_server_agent()


