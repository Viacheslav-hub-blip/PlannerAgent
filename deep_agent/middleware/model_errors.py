"""Обработка временных ошибок модели.

Содержит функции:
- is_retryable_model_error: определение ошибок, для которых допустим повторный вызов.
- format_model_error: формирование безопасного сообщения пользователю после неудачных попыток.

Содержит классы:
- ModelErrorMiddleware: преобразование окончательной ошибки провайдера в AI-сообщение.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError

MODEL_MAX_RETRIES = 5


def is_retryable_model_error(error: Exception) -> bool:
    """Определяет, следует ли повторить вызов модели.

    Args:
        error: Исключение, возникшее при обращении к модели.

    Returns:
        ``True`` для сетевых ошибок, таймаутов, rate limit и временных HTTP-ошибок
        провайдера; иначе ``False``.
    """

    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return True
    if not isinstance(error, APIStatusError):
        return False
    return error.status_code in {408, 409, 429} or error.status_code >= 500


def format_model_error(error: Exception) -> str:
    """Формирует безопасное сообщение о недоступности модели.

    Args:
        error: Последнее исключение после завершения повторных попыток.

    Returns:
        Русскоязычное сообщение для пользователя без технических деталей и секретов.
    """

    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return (
            "Не удалось подключиться к модели после нескольких попыток. "
            "Проверьте соединение и повторите запрос позже."
        )

    if isinstance(error, APIStatusError):
        status_code = error.status_code
        if status_code in {401, 403}:
            return (
                "Провайдер модели отклонил авторизацию. "
                "Проверьте настройки доступа к модели."
            )
        if status_code == 402:
            return (
                "Провайдер модели отклонил запрос из-за ограничений аккаунта. "
                "Проверьте доступность выбранной модели у провайдера."
            )
        if status_code == 429:
            return (
                "Модель временно перегружена. Выполнено несколько повторных попыток, "
                "но провайдер по-прежнему не принимает запрос. Повторите позже."
            )
        if status_code >= 500:
            return (
                "Провайдер модели временно недоступен. Выполнено несколько повторных "
                "попыток. Повторите запрос позже."
            )

    return (
        "Не удалось получить ответ модели. Запрос завершён с ошибкой; "
        "попробуйте повторить его позже."
    )


class ModelErrorMiddleware(AgentMiddleware):
    """Преобразует окончательную ошибку OpenAI-совместимого провайдера в ответ.

    Повторы выполняются самим клиентом ``ChatOpenAI``. Middleware вызывается после
    исчерпания попыток и не перехватывает ошибки программирования вне OpenAI SDK.
    """

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Синхронно обрабатывает окончательную ошибку модели.

        Args:
            request: Запрос LangChain к модели.
            handler: Следующий обработчик model call.

        Returns:
            Ответ модели либо безопасное AI-сообщение об ошибке провайдера.
        """

        try:
            return handler(request)
        except OpenAIError as error:
            return ModelResponse(result=[AIMessage(content=format_model_error(error))])

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Асинхронно обрабатывает окончательную ошибку модели.

        Args:
            request: Запрос LangChain к модели.
            handler: Следующий асинхронный обработчик model call.

        Returns:
            Ответ модели либо безопасное AI-сообщение об ошибке провайдера.
        """

        try:
            return await handler(request)
        except OpenAIError as error:
            return ModelResponse(result=[AIMessage(content=format_model_error(error))])


def build_model_error_middleware() -> ModelErrorMiddleware:
    """Собирает middleware окончательной ошибки модели.

    Returns:
        Настроенный ``ModelErrorMiddleware``.
    """

    return ModelErrorMiddleware()


__all__ = [
    "MODEL_MAX_RETRIES",
    "ModelErrorMiddleware",
    "build_model_error_middleware",
    "format_model_error",
    "is_retryable_model_error",
]
