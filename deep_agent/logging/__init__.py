"""Логирование статистики работы DeepAgent.

Содержит:
- PostgresLoggingMiddleware: middleware записи user/tool/final событий в PostgreSQL.
- build_postgres_logging_middleware: фабрика middleware по Python-конфигу.
"""

from deep_agent.logging.postgres import (
    PostgresLoggingMiddleware,
    build_postgres_logging_middleware,
)

__all__ = ["PostgresLoggingMiddleware", "build_postgres_logging_middleware"]
