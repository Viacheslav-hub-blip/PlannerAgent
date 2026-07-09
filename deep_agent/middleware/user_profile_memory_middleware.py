"""Middleware ленивой инициализации памяти профиля пользователя.

Содержит:
- UserProfileMemoryMiddleware: проверяет файл профиля при первом обращении к модели.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from deep_agent.memory.user_profile_memory import UserProfileMemory, ensure_user_profile_memory


@dataclass
class UserProfileMemoryMiddleware(AgentMiddleware):
    """Лениво создает файл памяти профиля пользователя перед первым model call.

    Args:
        profile: Ссылка на файл памяти и Store пользователя.
        spark_session_factory: Фабрика SparkSession из инструмента ``load_data``.

    Returns:
        Middleware, которое не выполняет Spark-запрос при загрузке graph.
    """

    profile: UserProfileMemory
    spark_session_factory: Any
    _initialized: bool = field(default=False, init=False, repr=False)
    _content: str | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Создает память профиля и добавляет ее в первый prompt.

        Args:
            request: Запрос к модели.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели.
        """

        return handler(self._with_user_profile(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Асинхронно создает память профиля и добавляет ее в первый prompt.

        Args:
            request: Запрос к модели.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели.
        """

        updated_request = await asyncio.to_thread(self._with_user_profile, request)
        return await handler(updated_request)

    def _with_user_profile(self, request: ModelRequest) -> ModelRequest:
        """Возвращает запрос модели с добавленным профилем пользователя.

        Args:
            request: Исходный запрос к модели.

        Returns:
            Исходный или обновленный запрос к модели.
        """

        content = self._ensure_content()
        if not content:
            return request
        return request.override(
            system_message=append_to_system_message(
                request.system_message,
                f"## Профиль текущего пользователя\n\n{content}",
            )
        )

    def _ensure_content(self) -> str | None:
        """Инициализирует память профиля не более одного раза на процесс.

        Args:
            Отсутствуют.

        Returns:
            Содержимое файла памяти профиля или ``None``.
        """

        if self._initialized:
            return self._content
        with self._lock:
            if self._initialized:
                return self._content
            try:
                self._content = ensure_user_profile_memory(
                    profile=self.profile,
                    spark_session_factory=self.spark_session_factory,
                )
            except Exception as error:
                print(
                    "[deep-agent] user profile memory disabled: "
                    f"{type(error).__name__}: {error}",
                    flush=True,
                )
                self._content = None
            self._initialized = True
            return self._content
