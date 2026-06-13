"""Тесты обработки ошибок модели.

Содержит классы:
- ModelErrorHandlingTests: проверка retry-классификации и безопасных сообщений.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import httpx
from openai import APIConnectionError, APIStatusError

from deep_agent.middleware.model_errors import (
    MODEL_MAX_RETRIES,
    ModelErrorMiddleware,
    build_model_error_middleware,
    format_model_error,
    is_retryable_model_error,
)


def _status_error(status_code: int) -> APIStatusError:
    """Создаёт локальную HTTP-ошибку OpenAI SDK.

    Args:
        status_code: HTTP-код ответа провайдера.

    Returns:
        ``APIStatusError`` без сетевого запроса.
    """

    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(status_code, request=request)
    return APIStatusError("provider error", response=response, body=None)


class ModelErrorHandlingTests(unittest.TestCase):
    """Проверяет правила повторов и пользовательские сообщения."""

    def test_retries_temporary_provider_errors(self) -> None:
        """Проверяет повторы для connection, rate limit и HTTP 5xx.

        Returns:
            ``None``.
        """

        request = httpx.Request("POST", "https://provider.invalid/chat")

        self.assertTrue(
            is_retryable_model_error(APIConnectionError(request=request))
        )
        for status_code in (408, 409, 429, 500, 503):
            self.assertTrue(is_retryable_model_error(_status_error(status_code)))

    def test_does_not_retry_permanent_provider_errors(self) -> None:
        """Проверяет отсутствие повторов для постоянных HTTP-ошибок.

        Returns:
            ``None``.
        """

        for status_code in (400, 401, 402, 403, 404):
            self.assertFalse(is_retryable_model_error(_status_error(status_code)))

    def test_formats_safe_user_messages(self) -> None:
        """Проверяет безопасные сообщения без исходного текста провайдера.

        Returns:
            ``None``.
        """

        unavailable = format_model_error(_status_error(503))
        account_restriction = format_model_error(_status_error(402))

        self.assertIn("временно недоступен", unavailable)
        self.assertIn("ограничений аккаунта", account_restriction)
        self.assertNotIn("provider error", unavailable)
        self.assertNotIn("provider error", account_restriction)

    def test_builds_final_error_handler_without_nested_retries(self) -> None:
        """Проверяет отсутствие вложенных повторов в agent middleware.

        Returns:
            ``None``.
        """

        middleware = build_model_error_middleware()

        self.assertEqual(MODEL_MAX_RETRIES, 5)
        self.assertIsInstance(middleware, ModelErrorMiddleware)

    def test_model_client_uses_shared_retry_limit(self) -> None:
        """Проверяет настройку повторов на общем клиенте модели.

        Returns:
            ``None``.
        """

        model_source = (Path(__file__).parents[1] / "model.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("max_retries=MODEL_MAX_RETRIES", model_source)

    def test_middleware_converts_only_provider_errors(self) -> None:
        """Проверяет преобразование ошибок провайдера без маскировки дефектов кода.

        Returns:
            ``None``.
        """

        middleware = build_model_error_middleware()

        response = middleware.wrap_model_call(
            None,  # type: ignore[arg-type]
            lambda _: (_ for _ in ()).throw(_status_error(503)),
        )
        self.assertIn("временно недоступен", str(response.result[0].content))

        with self.assertRaisesRegex(ValueError, "programming error"):
            middleware.wrap_model_call(
                None,  # type: ignore[arg-type]
                lambda _: (_ for _ in ()).throw(ValueError("programming error")),
            )


if __name__ == "__main__":
    unittest.main()
