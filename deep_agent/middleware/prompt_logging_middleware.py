"""Middleware сохранения итоговых system prompt перед вызовом модели.

Содержит:
- PromptLoggingMiddleware: запись system prompt каждого model call в текстовый файл.
- _message_content_to_text: преобразование content сообщения в текст для файла.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse


@dataclass(frozen=True)
class PromptLoggingMiddleware(AgentMiddleware):
    """Сохраняет system prompt, передаваемый следующему обработчику model call.

    Args:
        log_dir: Каталог для файлов с prompt. Создается при первом model call.
        agent_name: Имя агента, добавляемое в имя файла.

    Returns:
        Middleware, не изменяющий запрос и ответ модели.
    """

    log_dir: Path
    agent_name: str

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Сохраняет system prompt при синхронном вызове модели.

        Args:
            request: Итоговый запрос к модели после предыдущих middleware.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        self._save_system_prompt(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Сохраняет system prompt при асинхронном вызове модели.

        Args:
            request: Итоговый запрос к модели после предыдущих middleware.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        self._save_system_prompt(request)
        return await handler(request)

    def _save_system_prompt(self, request: ModelRequest) -> None:
        """Записывает system prompt запроса в отдельный UTF-8 файл.

        Args:
            request: Запрос к модели, содержащий system message.

        Returns:
            ``None``. Если system message отсутствует, файл не создается.
        """

        if request.system_message is None:
            return

        self.log_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"system_prompt_{self.agent_name}_{uuid4()}.txt"
        (self.log_dir / file_name).write_text(
            _message_content_to_text(request.system_message.content),
            encoding="utf-8",
        )


def _message_content_to_text(content: Any) -> str:
    """Преобразует строковое или блочное content сообщения в текст.

    Args:
        content: Содержимое LangChain-сообщения.

    Returns:
        Текстовое представление содержимого для записи в файл.
    """

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", block)) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


__all__ = ["PromptLoggingMiddleware"]
