"""Внутренняя конфигурация логирования пользовательских запросов.

Содержит:
- build_default_agent_request_logger: сборка штатного логгера запросов агента.
"""

from __future__ import annotations

import os

from deep_agent.middleware.request_logging_middleware import AgentRequestLogger

DB_POOL_RECYCLE = 3600
REQUEST_LOGGING_ENABLED = os.getenv(
    "DEEP_AGENT_REQUEST_LOGGING_ENABLED",
    "",
).strip().lower() in {"1", "true", "yes", "on"}
REQUEST_LOG_SCHEMA = os.getenv("DEEP_AGENT_REQUEST_LOG_SCHEMA", "user").strip() or "user"
REQUEST_LOG_TABLE = (
    os.getenv("DEEP_AGENT_REQUEST_LOG_TABLE", "agent_request_logs").strip()
    or "agent_request_logs"
)
CONNECTION_STRING = os.getenv("DEEP_AGENT_REQUEST_LOG_DSN", "").strip()


def build_default_agent_request_logger() -> AgentRequestLogger | None:
    """Собирает штатный логгер пользовательских запросов агента.

    Args:
        Отсутствуют. Параметры подключения читаются из переменных окружения
        ``DEEP_AGENT_REQUEST_LOGGING_ENABLED``, ``DEEP_AGENT_REQUEST_LOG_DSN``,
        ``DEEP_AGENT_REQUEST_LOG_SCHEMA`` и ``DEEP_AGENT_REQUEST_LOG_TABLE``.

    Returns:
        ``AgentRequestLogger`` для записи запросов в PostgreSQL или ``None``, если
        логирование отключено или строка подключения не передана.
    """

    if not REQUEST_LOGGING_ENABLED or not CONNECTION_STRING:
        return None
    return AgentRequestLogger(
        connection_string=CONNECTION_STRING,
        table_name=REQUEST_LOG_TABLE,
        schema_name=REQUEST_LOG_SCHEMA,
        pool_recycle=DB_POOL_RECYCLE,
        enabled=True,
    )


__all__ = ["build_default_agent_request_logger"]
