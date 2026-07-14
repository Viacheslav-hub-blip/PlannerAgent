"""Необязательная интеграция агента с локальной трассировкой Phoenix.

Содержит:
- initialize_phoenix_tracing: однократно регистрирует экспорт трасс в Phoenix.
- phoenix_tracing_context: добавляет пользователя и сессию к трассам одного запуска.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from functools import lru_cache
from typing import Any

LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def initialize_phoenix_tracing() -> Any | None:
    """Регистрирует асинхронный экспорт трасс в общий сервер Phoenix.

    Args:
        Отсутствуют. Параметры общего проекта и OTLP endpoint заданы внутри
        функции.

    Returns:
        Зарегистрированный ``TracerProvider`` или ``None``, если интеграцию
        Phoenix не удалось инициализировать.
    """

    try:
        from phoenix.otel import register

        return register(
            project_name="deepagents-shared",
            endpoint="http://127.0.0.1:6006/v1/traces",
            protocol="http/protobuf",
            auto_instrument=True,
            batch=True,
            verbose=False,
        )
    except Exception:
        LOGGER.warning(
            "Phoenix tracing недоступен; агент продолжит работу без трассировки.",
            exc_info=True,
        )
        return None


@contextmanager
def phoenix_tracing_context(*, user_id: str, thread_id: str) -> Iterator[None]:
    """Устанавливает атрибуты пользователя и чата на время запуска графа.

    Args:
        user_id: Канонический логин пользователя.
        thread_id: Идентификатор чата LangGraph Agent Server.

    Yields:
        Управление вызывающему коду внутри Phoenix-контекста. Если Phoenix
        недоступен или контекст не удалось создать, управление передается без
        трассировки.
    """

    normalized_user_id = str(user_id).strip()
    normalized_thread_id = str(thread_id).strip()
    if not normalized_user_id or not normalized_thread_id:
        yield
        return

    if initialize_phoenix_tracing() is None:
        with nullcontext():
            yield
        return

    attributes_context: Any
    try:
        from phoenix.otel import using_attributes

        session_id = f"{normalized_user_id}:{normalized_thread_id}"
        attributes_context = using_attributes(
            user_id=normalized_user_id,
            session_id=session_id,
            metadata={
                "user_id": normalized_user_id,
                "thread_id": normalized_thread_id,
                "environment": "shared-vm",
            },
            tags=["deepagents"],
        )
        attributes_context.__enter__()
    except Exception:
        LOGGER.warning(
            "Не удалось установить Phoenix-атрибуты; запуск продолжится без них.",
            exc_info=True,
        )
        with nullcontext():
            yield
        return

    try:
        yield
    finally:
        try:
            attributes_context.__exit__(None, None, None)
        except Exception:
            LOGGER.warning(
                "Не удалось закрыть Phoenix-контекст; результат агента не затронут.",
                exc_info=True,
            )
