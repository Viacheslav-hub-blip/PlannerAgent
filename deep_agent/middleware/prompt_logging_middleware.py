"""Middleware сохранения полного запроса перед вызовом модели.

Содержит:
- PromptLoggingMiddleware: запись полного ``ModelRequest`` каждого model call в JSON.
- _model_request_to_dict: преобразование ``ModelRequest`` в JSON-совместимую структуру.
- _tool_to_dict: сериализация инструмента из запроса модели.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import message_to_dict
from langchain_core.utils.function_calling import convert_to_openai_tool


@dataclass(frozen=True)
class PromptLoggingMiddleware(AgentMiddleware):
    """Сохраняет полный запрос, передаваемый следующему обработчику model call.

    Args:
        log_dir: Каталог для файлов с prompt. Создается при первом model call.
        agent_name: Имя агента, добавляемое в имя файла.

    Returns:
        Middleware, не изменяющий запрос и ответ модели. Файл содержит system prompt,
        сообщения, инструменты и параметры ``ModelRequest``.
    """

    log_dir: Path
    agent_name: str

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Сохраняет полный запрос при синхронном вызове модели.

        Args:
            request: Итоговый запрос к модели после предыдущих middleware.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        self._save_model_request(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Сохраняет полный запрос при асинхронном вызове модели.

        Args:
            request: Итоговый запрос к модели после предыдущих middleware.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели без изменений.
        """

        self._save_model_request(request)
        return await handler(request)

    def _save_model_request(self, request: ModelRequest) -> None:
        """Записывает полный ``ModelRequest`` в отдельный UTF-8 JSON-файл.

        Args:
            request: Итоговый запрос к модели после всех предыдущих middleware.

        Returns:
            ``None``.
        """

        self.log_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"model_request_{self.agent_name}_{uuid4()}.json"
        (self.log_dir / file_name).write_text(
            json.dumps(
                _model_request_to_dict(request),
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )


def _model_request_to_dict(request: ModelRequest) -> dict[str, Any]:
    """Преобразует ``ModelRequest`` в структуру, пригодную для JSON-записи.

    Args:
        request: Итоговый запрос, передаваемый в model handler.

    Returns:
        Словарь с системным сообщением, историей, инструментами и настройками модели.
    """

    return {
        "model": {
            "type": type(request.model).__name__,
            "identifier": getattr(
                request.model,
                "model_name",
                getattr(request.model, "model", None),
            ),
        },
        "system_message": (
            message_to_dict(request.system_message)
            if request.system_message is not None
            else None
        ),
        "messages": [message_to_dict(message) for message in request.messages],
        "tools": [_tool_to_dict(tool) for tool in request.tools],
        "tool_choice": request.tool_choice,
        "response_format": request.response_format,
        "model_settings": request.model_settings,
    }


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    """Преобразует инструмент из ``ModelRequest`` в его модельную схему.

    Args:
        tool: LangChain tool или словарь со схемой инструмента.

    Returns:
        OpenAI-совместимая схема tool либо ее строковое представление при ошибке.
    """

    try:
        return convert_to_openai_tool(tool)
    except (TypeError, ValueError) as error:
        return {"serialization_error": str(error), "repr": repr(tool)}


__all__ = ["PromptLoggingMiddleware"]
