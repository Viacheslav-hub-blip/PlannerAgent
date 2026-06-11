"""LangGraph entrypoint локального UI для аналитического DeepAgent.

Содержит функции:
- _required_environment: чтение обязательной переменной окружения.
- build_ui_model: сборка OpenAI-совместимой chat-модели LangChain.
- build_ui_agent: сборка графа агента для локального Agent Server.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.settings import load_deep_agent_settings
from tests.support.fake_spark_data import build_fake_spark_data_tools

ARTIFACTS_VIRTUAL_DIR = "/artifacts/"
UI_SYSTEM_PROMPT_SUFFIX = """
## Локальный UI

- Для многошаговой задачи сначала используй `write_todos` и обновляй статусы плана.
- Перед значимым действием можно дать пользователю короткое проверяемое резюме намерения
  или результата. Не раскрывай скрытую цепочку рассуждений.
- Текстовые артефакты, которые пользователь должен открыть в UI, сохраняй через
  `write_file` или `edit_file` в `/artifacts/`. Предпочитай `.md`, `.txt`, `.json` и `.csv`.
- Большие или бинарные локальные файлы не копируй в state. Покажи их путь в ответе
  или результате инструмента.
""".strip()


def _env_flag(name: str, *, default: bool = False) -> bool:
    """Читает булеву переменную окружения.

    Args:
        name: Имя переменной окружения.
        default: Значение при отсутствии переменной.

    Returns:
        Нормализованное булево значение.
    """

    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _required_environment(name: str) -> str:
    """Возвращает обязательную непустую переменную окружения.

    Args:
        name: Имя переменной окружения.

    Returns:
        Непустое строковое значение переменной.

    Raises:
        RuntimeError: Переменная отсутствует или содержит пустую строку.
    """

    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Не задана переменная {name}. Создайте local_ui/.env по примеру "
            "local_ui/.env.example."
        )
    return value


def build_ui_model() -> ChatOpenAI:
    """Собирает OpenAI-совместимую модель для supervisor и subagents.

    Returns:
        Настроенный ``ChatOpenAI``. Ключ читается только из ``OPENAI_API_KEY``.
    """

    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    model_kwargs: dict[str, Any] = {
        "model": _required_environment("DEEP_AGENT_MODEL"),
        "api_key": _required_environment("OPENAI_API_KEY"),
        "temperature": float(os.environ.get("DEEP_AGENT_TEMPERATURE", "0.1")),
        "timeout": float(os.environ.get("DEEP_AGENT_TIMEOUT", "120")),
        "max_retries": int(os.environ.get("DEEP_AGENT_MAX_RETRIES", "0")),
        "max_completion_tokens": int(
            os.environ.get("DEEP_AGENT_MAX_TOKENS", "8192")
        ),
    }
    if base_url:
        model_kwargs["base_url"] = base_url
    if _env_flag("DEEP_AGENT_DISABLE_STREAMING", default=True):
        model_kwargs["disable_streaming"] = True
    return ChatOpenAI(**model_kwargs)


def build_ui_agent() -> Any:
    """Собирает DeepAgent, совместимый с локальным LangGraph Agent Server.

    Returns:
        Скомпилированный граф без пользовательского checkpointer. Persistence,
        threads и streaming предоставляет Agent Server.
    """

    settings = load_deep_agent_settings()
    model = build_ui_model()
    data_tools = build_fake_spark_data_tools(query_parser_model=model)
    return build_analytics_deep_agent(
        model=model,
        settings=settings,
        data_tools=data_tools,
        checkpointer=None,
        state_artifacts_virtual_dir=ARTIFACTS_VIRTUAL_DIR,
        system_prompt_suffix=UI_SYSTEM_PROMPT_SUFFIX,
    )


agent = build_ui_agent()
