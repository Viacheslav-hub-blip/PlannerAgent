"""Middleware логирования пользовательских запросов к агенту.

Содержит:
- AgentRequestLogger: создание таблицы и запись запроса пользователя в PostgreSQL.
- AgentRequestLoggingMiddleware: middleware записи только пользовательского запроса.
- _latest_human_message: получение последнего human-сообщения из state.
- _message_content_to_text: преобразование содержимого сообщения в текст запроса.
- _resolve_user_login: извлечение логина пользователя из абсолютных путей процесса.
- _extract_login_from_path: извлечение цифрового логина из пути ``/home/<login>_...``.
- _quote_identifier: безопасное quoting SQL-идентификаторов.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime
from typing_extensions import NotRequired

from deep_agent.agent_state import AnalyticsAgentState


DEFAULT_REQUEST_LOG_TABLE = "agent_request_logs"
DEFAULT_REQUEST_LOG_SCHEMA = "user"
DEFAULT_DB_POOL_RECYCLE = 3600


class RequestLoggingState(AnalyticsAgentState):
    """State агента с идентификатором уже записанного пользовательского turn.

    Attributes:
        request_logged_user_turn_key: ID последнего human-сообщения, которое уже
            было записано в таблицу логирования.
    """

    request_logged_user_turn_key: NotRequired[Annotated[str, PrivateStateAttr]]


@dataclass
class AgentRequestLogger:
    """Пишет пользовательские запросы агента в PostgreSQL.

    Args:
        connection_string: SQLAlchemy connection string для PostgreSQL.
        table_name: Название таблицы логирования запросов.
        schema_name: Название схемы PostgreSQL или ``None`` для схемы по умолчанию.
        pool_recycle: Время recycle соединений SQLAlchemy в секундах.
        enabled: Нужно ли выполнять подключение и запись.

    Returns:
        Объект логгера, который лениво создает engine, таблицу и пишет запросы.
    """

    connection_string: str = ""
    table_name: str = DEFAULT_REQUEST_LOG_TABLE
    schema_name: str | None = DEFAULT_REQUEST_LOG_SCHEMA
    pool_recycle: int = DEFAULT_DB_POOL_RECYCLE
    enabled: bool = False
    _engine: Any | None = field(default=None, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def initialize(self) -> None:
        """Создает подключение и таблицу логирования, если логирование включено.

        Args:
            Отсутствуют.

        Returns:
            ``None``. После успешного выполнения engine готов к записи запросов.

        Raises:
            RuntimeError: Если SQLAlchemy недоступен или БД вернула ошибку.
        """

        if not self.enabled:
            return
        with self._lock:
            if self._initialized:
                return
            self._engine = self._build_engine()
            self._create_table()
            self._initialized = True

    def log_request(self, *, request_text: str, user_login: str) -> None:
        """Записывает один пользовательский запрос в таблицу.

        Args:
            request_text: Исходный текст задачи пользователя.
            user_login: Логин пользователя, отправившего запрос.

        Returns:
            ``None``. Ошибки записи пробрасываются вызывающему коду.
        """

        if not self.enabled or not request_text.strip():
            return
        self.initialize()
        if self._engine is None:
            return

        from sqlalchemy import text

        full_table_name = self._full_table_name()
        query = text(
            f"""
            INSERT INTO {full_table_name} (request_text, user_login, requested_at)
            VALUES (:request_text, :user_login, :requested_at)
            """
        )
        with self._engine.begin() as connection:
            connection.execute(
                query,
                {
                    "request_text": request_text,
                    "user_login": user_login,
                    "requested_at": datetime.now(timezone.utc),
                },
            )

    def _build_engine(self) -> Any:
        """Создает SQLAlchemy engine для PostgreSQL.

        Args:
            Отсутствуют.

        Returns:
            SQLAlchemy ``Engine`` с настроенным ``pool_recycle``.

        Raises:
            RuntimeError: Если строка подключения пуста или SQLAlchemy недоступен.
        """

        if not self.connection_string.strip():
            raise RuntimeError("Для логирования запросов не задан connection_string.")
        try:
            from sqlalchemy import create_engine
        except ImportError as error:
            raise RuntimeError(
                "Для логирования запросов нужен пакет sqlalchemy."
            ) from error
        return create_engine(
            self.connection_string,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=True,
        )

    def _create_table(self) -> None:
        """Создает схему и таблицу логирования, если они отсутствуют.

        Args:
            Отсутствуют.

        Returns:
            ``None``.
        """

        if self._engine is None:
            return

        from sqlalchemy import text

        schema_sql = ""
        if self.schema_name:
            schema_sql = f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(self.schema_name)};"

        table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._full_table_name()} (
            request_text TEXT NOT NULL,
            user_login TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL
        );
        """
        with self._engine.begin() as connection:
            if schema_sql:
                connection.execute(text(schema_sql))
            connection.execute(text(table_sql))

    def _full_table_name(self) -> str:
        """Возвращает полное SQL-имя таблицы с безопасным quoting.

        Args:
            Отсутствуют.

        Returns:
            Имя таблицы в формате ``"schema"."table"`` или ``"table"``.
        """

        table = _quote_identifier(self.table_name)
        if not self.schema_name:
            return table
        return f"{_quote_identifier(self.schema_name)}.{table}"


@dataclass
class AgentRequestLoggingMiddleware(AgentMiddleware[RequestLoggingState]):
    """Логирует только входящие пользовательские запросы supervisor-а.

    Args:
        request_logger: Логгер, который создает таблицу и пишет записи в БД.

    Returns:
        Middleware для подключения в supervisor graph.
    """

    request_logger: AgentRequestLogger

    state_schema = RequestLoggingState

    def before_agent(
        self,
        state: RequestLoggingState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Записывает последний новый human-запрос перед запуском агента.

        Args:
            state: Текущий state агента с историей сообщений.
            runtime: Runtime текущего запуска LangGraph.

        Returns:
            Обновление state с ключом записанного turn или ``None``.
        """

        message = _latest_human_message(state)
        if message is None:
            return None

        user_turn_key = str(getattr(message, "id", "") or f"content:{getattr(message, 'content', '')}")
        if not user_turn_key or state.get("request_logged_user_turn_key") == user_turn_key:
            return None

        request_text = _message_content_to_text(getattr(message, "content", ""))
        if not request_text.strip():
            return None

        del runtime
        user_login = _resolve_user_login()
        try:
            self.request_logger.log_request(
                request_text=request_text,
                user_login=user_login,
            )
        except Exception as error:
            print(
                "[agent-request-logger] failed "
                f"error={type(error).__name__}: {error}",
                flush=True,
            )
        return {"request_logged_user_turn_key": user_turn_key}

    async def abefore_agent(
        self,
        state: RequestLoggingState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Асинхронно записывает последний новый human-запрос перед запуском агента.

        Args:
            state: Текущий state агента с историей сообщений.
            runtime: Runtime текущего запуска LangGraph.

        Returns:
            Обновление state с ключом записанного turn или ``None``.
        """

        return await asyncio.to_thread(self.before_agent, state, runtime)


def _latest_human_message(state: RequestLoggingState) -> Any | None:
    """Возвращает последнее human-сообщение из state.

    Args:
        state: State агента с историей сообщений.

    Returns:
        Последнее сообщение пользователя или ``None``.
    """

    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage) or getattr(message, "type", None) == "human":
            return message
    return None


def _message_content_to_text(content: Any) -> str:
    """Преобразует content LangChain-сообщения в текст запроса.

    Args:
        content: Строка, список content-блоков или произвольное значение.

    Returns:
        Текстовое представление пользовательского запроса.
    """

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part.strip())
    return str(content)


def _resolve_user_login() -> str:
    """Определяет логин пользователя из абсолютных путей процесса.

    Args:
        Отсутствуют. Функция проверяет текущую директорию и ``sys.path``.

    Returns:
        Цифровой логин из префикса ``/home/<login>_...`` или ``unknown``.
    """

    candidates = [Path.cwd().as_posix(), *(str(path) for path in sys.path)]
    for candidate in candidates:
        login = _extract_login_from_path(candidate)
        if login:
            return login
    return "unknown"


def _extract_login_from_path(path: str) -> str:
    """Извлекает цифровой логин из абсолютного пути пользователя.

    Args:
        path: Абсолютный путь, который начинается с ``/home/<login>_...``.

    Returns:
        Цифровой логин или пустую строку, если путь не соответствует шаблону.
    """

    match = re.match(r"^/home/(\d+)_", str(path))
    if match is None:
        return ""
    return match.group(1)


def _quote_identifier(value: str) -> str:
    """Безопасно заключает SQL-идентификатор в двойные кавычки.

    Args:
        value: Название схемы или таблицы.

    Returns:
        SQL-идентификатор в двойных кавычках.

    Raises:
        ValueError: Если идентификатор пустой или содержит недопустимые символы.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError("SQL identifier must be a non-empty string.")
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"Invalid SQL identifier: {normalized}")
    return f'"{normalized}"'


__all__ = [
    "AgentRequestLogger",
    "AgentRequestLoggingMiddleware",
    "RequestLoggingState",
]
