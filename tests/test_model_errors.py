"""Тесты встроенного middleware повторов модели.

Содержит классы:
- ModelErrorHandlingTests: проверка конфигурации ``ModelRetryMiddleware``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import httpx
from langchain.agents.middleware import ModelRetryMiddleware
from openai import APIStatusError

from deep_agent.agent import _build_native_runtime_middleware
from deep_agent.middleware.model_errors import format_model_error, is_retryable_model_error
from deep_agent.middleware.tool_output_file import ToolOutputFileMiddleware
from deep_agent.settings import load_deep_agent_settings


def _status_error(status_code: int, message: str = "provider error") -> APIStatusError:
    """Создаёт локальную HTTP-ошибку OpenAI SDK без сетевого запроса.

    Args:
        status_code: HTTP-код тестового ответа.
        message: Текст тестовой ошибки.

    Returns:
        Экземпляр ``APIStatusError`` с локальным ``httpx.Response``.
    """

    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(status_code, request=request)
    return APIStatusError(message, response=response, body=None)


class ModelErrorHandlingTests(unittest.TestCase):
    """Проверяет переход на встроенный ``ModelRetryMiddleware``."""

    def test_builds_native_retry_middleware(self) -> None:
        """Проверяет наличие встроенного retry middleware.

        Returns:
            ``None``.
        """

        settings = load_deep_agent_settings()
        middleware = _build_native_runtime_middleware(
            settings,
            ToolOutputFileMiddleware(output_dir=settings.tool_outputs_dir),
            limit_model_calls=False,
        )
        retry = next(item for item in middleware if isinstance(item, ModelRetryMiddleware))

        self.assertEqual(retry.max_retries, settings.max_model_retries)
        self.assertIs(retry.retry_on, is_retryable_model_error)
        self.assertIs(retry.on_failure, format_model_error)

    def test_formats_visible_error_and_masks_api_key(self) -> None:
        """Проверяет пользовательскую диагностику без утечки API-ключа.

        Returns:
            ``None``.
        """

        message = format_model_error(
            _status_error(401, "api_key=test-secret-value-123456")
        )

        self.assertIn("отклонил авторизацию", message)
        self.assertIn("HTTP-код: `401`", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn("test-secret-value-123456", message)

    def test_retry_middleware_returns_visible_ai_message(self) -> None:
        """Проверяет преобразование финальной ошибки в сообщение для UI.

        Returns:
            ``None``.
        """

        settings = load_deep_agent_settings()
        middleware = _build_native_runtime_middleware(
            settings,
            ToolOutputFileMiddleware(output_dir=settings.tool_outputs_dir),
            limit_model_calls=False,
        )
        retry = next(item for item in middleware if isinstance(item, ModelRetryMiddleware))

        response = retry.wrap_model_call(
            None,  # type: ignore[arg-type]
            lambda _: (_ for _ in ()).throw(_status_error(401)),
        )

        content = str(response.result[0].content)
        self.assertIn("отклонил авторизацию", content)
        self.assertIn("HTTP-код: `401`", content)

    def test_model_client_uses_shared_retry_limit(self) -> None:
        """Проверяет настройку повторов на общем клиенте модели.

        Returns:
            ``None``.
        """

        model_source = (Path(__file__).parents[1] / "model.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('os.environ.get("OPENAI_API_KEY")', model_source)
        self.assertNotRegex(model_source, r"sk-[A-Za-z0-9_-]{12,}")


if __name__ == "__main__":
    unittest.main()
