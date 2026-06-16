"""Python-конфигурация PostgreSQL logging для DeepAgent.

Содержит:
- PostgresLoggingConfig: параметры подключения и таблиц логирования.
- build_postgres_logging_config: сборка конфигурации из констант файла.
- initialize_postgres_logging: создание схемы и таблиц PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass

POSTGRES_LOGGING_ENABLED = False
POSTGRES_DSN = "postgresql://user:password@localhost:5432/deepagent"
POSTGRES_SCHEMA = "deep_agent_logs"
POSTGRES_AGENT_RUNS_TABLE = "agent_runs"
POSTGRES_TOOL_EVENTS_TABLE = "agent_tool_events"


@dataclass(frozen=True)
class PostgresLoggingConfig:
    """Параметры подключения и таблиц PostgreSQL logging.

    Attributes:
        enabled: Включено ли логирование.
        dsn: PostgreSQL DSN для подключения.
        schema_name: Имя схемы PostgreSQL.
        runs_table: Имя таблицы запусков агента.
        tool_events_table: Имя таблицы событий инструментов.
    """

    enabled: bool
    dsn: str
    schema_name: str
    runs_table: str
    tool_events_table: str


def build_postgres_logging_config() -> PostgresLoggingConfig:
    """Собирает конфигурацию PostgreSQL logging из Python-констант.

    Returns:
        Готовая конфигурация логирования.
    """

    return PostgresLoggingConfig(
        enabled=POSTGRES_LOGGING_ENABLED,
        dsn=POSTGRES_DSN,
        schema_name=POSTGRES_SCHEMA,
        runs_table=POSTGRES_AGENT_RUNS_TABLE,
        tool_events_table=POSTGRES_TOOL_EVENTS_TABLE,
    )


def initialize_postgres_logging(
    config: PostgresLoggingConfig | None = None,
) -> None:
    """Создаёт схему и таблицы PostgreSQL для логирования.

    Args:
        config: Конфигурация подключения. Если ``None``, используются константы файла.

    Returns:
        ``None``. При выключенном ``enabled`` функция ничего не делает.
    """

    if config is None:
        config = build_postgres_logging_config()
    if not config.enabled:
        return

    from deep_agent.logging.postgres import PostgresAgentLogRepository

    PostgresAgentLogRepository(config).ensure_schema()


__all__ = [
    "POSTGRES_AGENT_RUNS_TABLE",
    "POSTGRES_DSN",
    "POSTGRES_LOGGING_ENABLED",
    "POSTGRES_SCHEMA",
    "POSTGRES_TOOL_EVENTS_TABLE",
    "PostgresLoggingConfig",
    "build_postgres_logging_config",
    "initialize_postgres_logging",
]
