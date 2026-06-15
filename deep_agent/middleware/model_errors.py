"""Обработка временных ошибок модели.

Содержит функции:
- is_retryable_model_error: определение ошибок, для которых допустим повторный вызов.
- format_model_error: формирование сообщения пользователю после неудачных попыток.
- _format_error_details: формирование технического блока ошибки.
- _redact_sensitive_data: маскирование секретов в тексте исключения.

"""

from __future__ import annotations

import re

from openai import APIConnectionError, APIStatusError, APITimeoutError

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)[^,\s}\"']+"),
    re.compile(r"(?i)(/keys/)[A-Za-z0-9_-]{12,}"),
)


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
    """Формирует пользовательское сообщение с техническими деталями ошибки.

    Args:
        error: Последнее исключение после завершения повторных попыток.

    Returns:
        Русскоязычное пояснение и очищенный технический блок ошибки.
    """

    if isinstance(error, (APIConnectionError, APITimeoutError)):
        summary = (
            "Не удалось подключиться к модели после нескольких попыток. "
            "Проверьте соединение и повторите запрос позже."
        )
    elif isinstance(error, APIStatusError):
        status_code = error.status_code
        if status_code in {401, 403}:
            summary = (
                "Провайдер модели отклонил авторизацию. "
                "Проверьте настройки доступа к модели."
            )
        elif status_code == 402:
            summary = (
                "Провайдер модели отклонил запрос из-за ограничений аккаунта. "
                "Проверьте доступность выбранной модели у провайдера."
            )
        elif status_code == 429:
            summary = (
                "Модель временно перегружена. Выполнено несколько повторных попыток, "
                "но провайдер по-прежнему не принимает запрос. Повторите позже."
            )
        elif status_code >= 500:
            summary = (
                "Провайдер модели временно недоступен. Выполнено несколько повторных "
                "попыток. Повторите запрос позже."
            )
        else:
            summary = (
                "Не удалось получить ответ модели. Провайдер отклонил запрос; "
                "проверьте технические детали ниже."
            )
    else:
        summary = (
            "Не удалось получить ответ модели. Запрос завершён с ошибкой; "
            "попробуйте повторить его позже."
        )
    return f"{summary}\n\n{_format_error_details(error)}"


def _format_error_details(error: Exception) -> str:
    """Формирует технический блок ошибки для отображения в чате.

    Args:
        error: Исключение провайдера модели.

    Returns:
        Markdown-блок с типом, HTTP-кодом и очищенным текстом исключения.
    """

    lines = [f"- Тип: `{type(error).__name__}`"]
    if isinstance(error, APIStatusError):
        lines.append(f"- HTTP-код: `{error.status_code}`")
    lines.append(f"- Сообщение: `{_redact_sensitive_data(str(error))}`")
    return "**Технические детали**\n\n" + "\n".join(lines)


def _redact_sensitive_data(value: str) -> str:
    """Маскирует секреты и чувствительные идентификаторы в тексте ошибки.

    Args:
        value: Исходный текст исключения.

    Returns:
        Текст с заменёнными API-ключами и идентификаторами ключей.
    """

    redacted = value
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(api"):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        elif pattern.pattern.startswith("(?i)(/keys/"):
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


__all__ = [
    "format_model_error",
    "is_retryable_model_error",
]
