"""Минимальный запуск аналитического DeepAgent.

Содержит:
- main: инициализация Spark session, инструмента чтения данных, агента и один invoke.
- _last_message_text: извлечение текста последнего ответа агента.
"""

from __future__ import annotations

from typing import Any

from pyspark.sql import SparkSession

from deep_agent_test import build_analytics_deep_agent, build_spark_data_tools, load_deep_agent_settings
from model import model

USER_MESSAGE = "что делал клиент в день сработки и за день до сработки? id сработки 3486d84b-4eba-4ba4-b044-94764fc9e7a4"


def main() -> int:
    """Запускает один запрос к агенту.

    Args:
        Отсутствуют. Скрипт не принимает параметры командной строки.

    Returns:
        Код завершения процесса: ``0`` при успешном invoke.
    """

    spark = SparkSession.builder.appName("analytics-deep-agent").getOrCreate()
    settings = load_deep_agent_settings()
    data_tools = build_spark_data_tools(spark)
    agent = build_analytics_deep_agent(model=model, settings=settings, data_tools=data_tools)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": USER_MESSAGE}]},
        config={
            "configurable": {"thread_id": settings.thread_id},
            "recursion_limit": settings.graph_recursion_limit,
        },
    )
    print(_last_message_text(result))
    return 0


def _last_message_text(result: Any) -> str:
    """Достает текст последнего сообщения агента из результата invoke.

    Args:
        result: Словарь состояния, который вернул ``agent.invoke``.

    Returns:
        Текст последнего сообщения или строковое представление результата.
    """

    if not isinstance(result, dict):
        return str(result)
    messages = result.get("messages") or []
    if not messages:
        return str(result)
    last_message = messages[-1]
    text = getattr(last_message, "text", None)
    if isinstance(text, str) and text:
        return text
    content = getattr(last_message, "content", None)
    if isinstance(content, str):
        return content
    return str(last_message)


if __name__ == "__main__":
    raise SystemExit(main())
