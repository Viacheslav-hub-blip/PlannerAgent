"""Middleware ленивой инициализации памяти профиля пользователя.

Содержит:
- UserProfileMemoryMiddleware: создает файл профиля до штатной загрузки памяти.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from deep_agent.memory.user_profile_memory import UserProfileMemory, ensure_user_profile_memory


@dataclass
class UserProfileMemoryMiddleware(AgentMiddleware):
    """Лениво создает файл памяти профиля пользователя перед загрузкой памяти.

    Args:
        profile: Ссылка на файл памяти профиля пользователя.
        spark_session_factory: Фабрика SparkSession из инструмента ``load_data``.

    Returns:
        Middleware, которое не выполняет Spark-запрос при загрузке graph.
    """

    profile: UserProfileMemory
    spark_session_factory: Any
    _initialized: bool = field(default=False, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: Any,
    ) -> None:
        """Создает память профиля до штатного чтения файлов памяти deepagents.

        Args:
            state: Текущее состояние агента.
            runtime: Runtime текущего запуска.
            config: Конфигурация текущего запуска.

        Returns:
            None.
        """

        self._ensure_memory()
        return None

    async def abefore_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: Any,
    ) -> None:
        """Асинхронно создает память профиля до штатного чтения файлов памяти.

        Args:
            state: Текущее состояние агента.
            runtime: Runtime текущего запуска.
            config: Конфигурация текущего запуска.

        Returns:
            None.
        """

        await asyncio.to_thread(self._ensure_memory)
        return None

    def _ensure_memory(self) -> None:
        """Инициализирует память профиля не более одного раза на процесс.

        Args:
            Отсутствуют.

        Returns:
            None.
        """

        if self._initialized:
            return None
        with self._lock:
            if self._initialized:
                return None
            try:
                ensure_user_profile_memory(
                    profile=self.profile,
                    spark_session_factory=self.spark_session_factory,
                )
            except Exception as error:
                print(
                    "[deep-agent] user profile memory disabled: "
                    f"{type(error).__name__}: {error}",
                    flush=True,
                )
            self._initialized = True
            return None
