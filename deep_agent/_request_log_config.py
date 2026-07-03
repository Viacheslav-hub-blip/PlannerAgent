"""Внутренняя конфигурация логирования пользовательских запросов.

Содержит:
- build_default_agent_request_logger: сборка штатного логгера запросов агента.
"""

from __future__ import annotations

from deep_agent.middleware.request_logging_middleware import AgentRequestLogger

DB_POOL_RECYCLE = 3600
REQUEST_LOGGING_ENABLED = True
REQUEST_LOG_SCHEMA = "user"
REQUEST_LOG_TABLE = "agent_request_logs"
CONNECTION_STRING = (
    "postgresql+psycopg2://ci04257537_pg_kv_user:"
    "QPzXJhf3ax_Ytf8kBZgyI244B@pvlod-lab000030.cloud.omega.sbrf.ru:"
    "5433/lab_antifraud_rag_postgre"
)


def build_default_agent_request_logger() -> AgentRequestLogger | None:
    """Собирает штатный логгер пользовательских запросов агента.

    Args:
        Отсутствуют. Все параметры подключения заданы константами этого модуля.

    Returns:
        ``AgentRequestLogger`` для записи запросов в PostgreSQL или ``None``, если
        логирование отключено константой ``REQUEST_LOGGING_ENABLED``.
    """

    if not REQUEST_LOGGING_ENABLED:
        return None
    return AgentRequestLogger(
        connection_string=CONNECTION_STRING,
        table_name=REQUEST_LOG_TABLE,
        schema_name=REQUEST_LOG_SCHEMA,
        pool_recycle=DB_POOL_RECYCLE,
        enabled=True,
    )


__all__ = ["build_default_agent_request_logger"]
