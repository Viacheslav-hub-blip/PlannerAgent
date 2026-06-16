"""PostgreSQL logging middleware для статистики DeepAgent.

Содержит:
- PostgresAgentLogRepository: низкоуровневые операции записи в PostgreSQL.
- PostgresLoggingMiddleware: LangChain middleware логирования запусков и tools.
- build_postgres_logging_middleware: фабрика middleware по Python-конфигу.
- _serialize_json: сериализация параметров tool в JSON-совместимое значение.
- _message_text: извлечение текста из сообщения.
- _latest_human_message_text: поиск последнего пользовательского сообщения.
- _latest_ai_message_text: поиск последнего ответа ассистента.
- _validate_identifier: проверка имени SQL identifier.
"""

from __future__ import annotations

import json
import re
import uuid
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from deep_agent.logging.postgres_config import (
    PostgresLoggingConfig,
    build_postgres_logging_config,
)
from deep_agent.state import AnalyticsAgentState, extract_state_messages


class PostgresAgentLogRepository:
    """Репозиторий записи статистики DeepAgent в PostgreSQL.

    Args:
        config: Параметры подключения и таблиц PostgreSQL.
    """

    def __init__(self, config: PostgresLoggingConfig) -> None:
        """Сохраняет конфигурацию репозитория.

        Args:
            config: Параметры подключения и таблиц PostgreSQL.

        Returns:
            ``None``.
        """

        self.config = config
        self.schema_name = _validate_identifier(config.schema_name)
        self.runs_table = _validate_identifier(config.runs_table)
        self.tool_events_table = _validate_identifier(config.tool_events_table)

    def ensure_schema(self) -> None:
        """Создаёт схему и таблицы логирования, если они отсутствуют.

        Returns:
            ``None``.
        """

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema_name}.{self.runs_table} (
                        run_id uuid PRIMARY KEY,
                        thread_id text,
                        agent_name text NOT NULL,
                        user_request text,
                        final_answer text,
                        started_at timestamptz NOT NULL DEFAULT now(),
                        finished_at timestamptz
                    )
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.schema_name}.{self.tool_events_table} (
                        event_id uuid PRIMARY KEY,
                        run_id uuid REFERENCES {self.schema_name}.{self.runs_table}(run_id),
                        agent_name text NOT NULL,
                        tool_call_id text,
                        tool_name text NOT NULL,
                        status text NOT NULL,
                        args_json jsonb,
                        result_text text,
                        error_text text,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        completed_at timestamptz
                    )
                    """
                )

    def start_run(
        self,
        *,
        run_id: str,
        thread_id: str | None,
        agent_name: str,
        user_request: str,
    ) -> None:
        """Записывает начало запуска агента.

        Args:
            run_id: Идентификатор запуска.
            thread_id: Идентификатор LangGraph thread.
            agent_name: Имя агента или subagent.
            user_request: Текст пользовательского запроса или делегированной задачи.

        Returns:
            ``None``.
        """

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {self.schema_name}.{self.runs_table}
                        (run_id, thread_id, agent_name, user_request)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    (run_id, thread_id, agent_name, user_request),
                )

    def finish_run(self, *, run_id: str, final_answer: str) -> None:
        """Записывает финальный ответ запуска агента.

        Args:
            run_id: Идентификатор запуска.
            final_answer: Последний текстовый ответ ассистента.

        Returns:
            ``None``.
        """

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {self.schema_name}.{self.runs_table}
                    SET final_answer = %s, finished_at = now()
                    WHERE run_id = %s
                    """,
                    (final_answer, run_id),
                )

    def start_tool_event(
        self,
        *,
        event_id: str,
        run_id: str,
        agent_name: str,
        tool_call_id: str,
        tool_name: str,
        args: Any,
    ) -> None:
        """Записывает начало tool-вызова.

        Args:
            event_id: Идентификатор события tool.
            run_id: Идентификатор запуска агента.
            agent_name: Имя агента или subagent.
            tool_call_id: Идентификатор tool call от модели.
            tool_name: Имя инструмента.
            args: Аргументы tool.

        Returns:
            ``None``.
        """

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {self.schema_name}.{self.tool_events_table}
                        (event_id, run_id, agent_name, tool_call_id, tool_name, status, args_json)
                    VALUES (%s, %s, %s, %s, %s, 'started', %s::jsonb)
                    """,
                    (
                        event_id,
                        run_id,
                        agent_name,
                        tool_call_id,
                        tool_name,
                        json.dumps(_serialize_json(args), ensure_ascii=False, default=str),
                    ),
                )

    def finish_tool_event(
        self,
        *,
        event_id: str,
        status: str,
        result_text: str = "",
        error_text: str = "",
    ) -> None:
        """Записывает завершение tool-вызова.

        Args:
            event_id: Идентификатор события tool.
            status: Финальный статус ``completed`` или ``error``.
            result_text: Полный текст результата tool.
            error_text: Текст ошибки tool.

        Returns:
            ``None``.
        """

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {self.schema_name}.{self.tool_events_table}
                    SET status = %s,
                        result_text = %s,
                        error_text = %s,
                        completed_at = now()
                    WHERE event_id = %s
                    """,
                    (status, result_text, error_text, event_id),
                )

    def _connect(self) -> Any:
        """Открывает PostgreSQL-соединение.

        Returns:
            Объект соединения ``psycopg`` с ``autocommit=True``.

        Raises:
            ImportError: Пакет ``psycopg`` не установлен.
        """

        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "Для PostgreSQL logging установите пакет psycopg или psycopg[binary]."
            ) from exc
        return psycopg.connect(self.config.dsn, autocommit=True)


@dataclass
class PostgresLoggingMiddleware(AgentMiddleware[AnalyticsAgentState]):
    """Middleware записи user request, tool events и final answer в PostgreSQL.

    Args:
        repository: Репозиторий записи в PostgreSQL.
        agent_name: Имя агента, для которого установлен middleware.
        enabled: Включено ли фактическое логирование.
    """

    repository: PostgresAgentLogRepository
    agent_name: str = "supervisor"
    enabled: bool = False

    state_schema = AnalyticsAgentState

    def before_agent(
        self,
        state: AnalyticsAgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Логирует начало запуска агента и сохраняет run_id в state.

        Args:
            state: Текущий state агента.
            runtime: Runtime LangGraph с thread/run metadata.

        Returns:
            Обновление state с ``postgres_logging_run_id`` или ``None``.
        """

        if not self.enabled:
            return None
        run_id = state.get("postgres_logging_run_id") or str(uuid.uuid4())
        thread_id = getattr(runtime.execution_info, "thread_id", None)
        user_request = _latest_human_message_text(extract_state_messages(state))
        self._safe_call(
            self.repository.start_run,
            run_id=run_id,
            thread_id=thread_id,
            agent_name=self.agent_name,
            user_request=user_request,
        )
        return {"postgres_logging_run_id": run_id}

    async def abefore_agent(
        self,
        state: AnalyticsAgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Асинхронная обёртка для логирования начала запуска агента.

        Args:
            state: Текущий state агента.
            runtime: Runtime LangGraph с thread/run metadata.

        Returns:
            Обновление state с ``postgres_logging_run_id`` или ``None``.
        """

        return self.before_agent(state, runtime)

    def after_agent(
        self,
        state: AnalyticsAgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Логирует финальный ответ агента.

        Args:
            state: Финальный state агента.
            runtime: Runtime LangGraph.

        Returns:
            ``None``.
        """

        del runtime
        if not self.enabled:
            return None
        run_id = state.get("postgres_logging_run_id")
        if not run_id:
            return None
        final_answer = _latest_ai_message_text(extract_state_messages(state))
        self._safe_call(
            self.repository.finish_run,
            run_id=run_id,
            final_answer=final_answer,
        )
        return None

    async def aafter_agent(
        self,
        state: AnalyticsAgentState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """Асинхронная обёртка для логирования финального ответа агента.

        Args:
            state: Финальный state агента.
            runtime: Runtime LangGraph.

        Returns:
            ``None``.
        """

        return self.after_agent(state, runtime)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Логирует параметры, результат и ошибку одного tool-вызова.

        Args:
            request: Запрос tool call.
            handler: Следующий обработчик tool call.

        Returns:
            Результат исходного tool call.
        """

        if not self.enabled:
            return handler(request)
        event_id = str(uuid.uuid4())
        self._log_tool_start(request, event_id)
        try:
            result = handler(request)
        except Exception as exc:
            self._log_tool_finish(event_id, status="error", error_text=str(exc))
            raise
        self._log_tool_result(event_id, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Асинхронно логирует параметры, результат и ошибку одного tool-вызова.

        Args:
            request: Запрос tool call.
            handler: Следующий асинхронный обработчик tool call.

        Returns:
            Результат исходного tool call.
        """

        if not self.enabled:
            return await handler(request)
        event_id = str(uuid.uuid4())
        self._log_tool_start(request, event_id)
        try:
            result = await handler(request)
        except Exception as exc:
            self._log_tool_finish(event_id, status="error", error_text=str(exc))
            raise
        self._log_tool_result(event_id, result)
        return result

    def _log_tool_start(self, request: ToolCallRequest, event_id: str) -> None:
        """Записывает начало tool-вызова.

        Args:
            request: Запрос tool call.
            event_id: Идентификатор события.

        Returns:
            ``None``.
        """

        tool_call = request.tool_call or {}
        state = getattr(request, "state", {}) or {}
        run_id = (
            state.get("postgres_logging_run_id")
            if isinstance(state, dict)
            else getattr(state, "postgres_logging_run_id", None)
        )
        if not run_id:
            return
        self._safe_call(
            self.repository.start_tool_event,
            event_id=event_id,
            run_id=run_id,
            agent_name=self.agent_name,
            tool_call_id=str(tool_call.get("id") or ""),
            tool_name=str(tool_call.get("name") or "tool"),
            args=tool_call.get("args") or {},
        )

    def _log_tool_result(
        self,
        event_id: str,
        result: ToolMessage | Command[Any],
    ) -> None:
        """Записывает результат tool-вызова.

        Args:
            event_id: Идентификатор события.
            result: Результат tool call.

        Returns:
            ``None``.
        """

        if isinstance(result, ToolMessage):
            status = "error" if result.status == "error" else "completed"
            self._log_tool_finish(
                event_id,
                status=status,
                result_text=_message_text(result),
                error_text=_message_text(result) if status == "error" else "",
            )
            return
        self._log_tool_finish(event_id, status="completed", result_text=str(result))

    def _log_tool_finish(
        self,
        event_id: str,
        *,
        status: str,
        result_text: str = "",
        error_text: str = "",
    ) -> None:
        """Записывает завершение tool-вызова.

        Args:
            event_id: Идентификатор события.
            status: Финальный статус.
            result_text: Текст результата.
            error_text: Текст ошибки.

        Returns:
            ``None``.
        """

        self._safe_call(
            self.repository.finish_tool_event,
            event_id=event_id,
            status=status,
            result_text=result_text,
            error_text=error_text,
        )

    def _safe_call(self, func: Callable[..., Any], **kwargs: Any) -> None:
        """Выполняет запись лога без падения основного агента.

        Args:
            func: Метод репозитория.
            **kwargs: Аргументы метода репозитория.

        Returns:
            ``None``. Ошибка превращается в предупреждение.
        """

        try:
            func(**kwargs)
        except Exception as exc:
            warnings.warn(f"PostgreSQL logging отключен для события: {exc}", RuntimeWarning, stacklevel=2)


def build_postgres_logging_middleware(
    *,
    agent_name: str,
    config: PostgresLoggingConfig | None = None,
) -> PostgresLoggingMiddleware | None:
    """Создаёт PostgreSQL logging middleware по Python-конфигу.

    Args:
        agent_name: Имя агента или subagent.
        config: Конфигурация логирования. Если ``None``, читается Python-конфиг.

    Returns:
        Middleware при включённом logging или ``None`` при выключенном.
    """

    config = config or build_postgres_logging_config()
    if not config.enabled:
        return None
    repository = PostgresAgentLogRepository(config)
    return PostgresLoggingMiddleware(
        repository=repository,
        agent_name=agent_name,
        enabled=True,
    )


def _serialize_json(value: Any) -> Any:
    """Преобразует значение в JSON-совместимую структуру.

    Args:
        value: Произвольное значение из аргументов tool.

    Returns:
        JSON-совместимое значение.
    """

    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return value
    except TypeError:
        return str(value)


def _message_text(message: Any) -> str:
    """Извлекает текст из LangChain-сообщения или произвольного результата.

    Args:
        message: Сообщение или результат tool.

    Returns:
        Строковое представление содержимого.
    """

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except TypeError:
        return str(content)


def _latest_human_message_text(messages: list[Any]) -> str:
    """Возвращает текст последнего HumanMessage.

    Args:
        messages: Список сообщений state.

    Returns:
        Текст последнего пользовательского сообщения или пустая строка.
    """

    for message in reversed(messages):
        if isinstance(message, HumanMessage) or getattr(message, "type", None) == "human":
            return _message_text(message)
    return ""


def _latest_ai_message_text(messages: list[Any]) -> str:
    """Возвращает текст последнего AIMessage.

    Args:
        messages: Список сообщений state.

    Returns:
        Текст последнего ответа ассистента или пустая строка.
    """

    for message in reversed(messages):
        if isinstance(message, AIMessage) or getattr(message, "type", None) == "ai":
            return _message_text(message)
    return ""


def _validate_identifier(value: str) -> str:
    """Проверяет имя SQL schema/table на безопасный формат identifier.

    Args:
        value: Имя schema или table.

    Returns:
        Исходное имя.

    Raises:
        ValueError: Имя содержит недопустимые символы.
    """

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Некорректный SQL identifier: {value}")
    return value


__all__ = [
    "PostgresAgentLogRepository",
    "PostgresLoggingMiddleware",
    "build_postgres_logging_middleware",
]
