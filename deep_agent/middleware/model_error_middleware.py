"""Обработка временных ошибок модели.

Содержит функции:
- is_retryable_model_error: определение ошибок, для которых допустим повторный вызов.
- format_model_error: формирование сообщения пользователю после неудачных попыток.
- _is_connection_or_timeout_error: проверка сетевой ошибки или timeout без SDK-зависимости.
- _extract_provider_status_code: извлечение фактического статуса из вложенной ошибки proxy/SDK.
- _collect_status_codes: обход атрибутов исключения и DTO ответа провайдера.
- _status_codes_from_text: извлечение кодов провайдера из строкового представления ошибки.
- _is_retryable_status_code: проверка временного HTTP-подобного кода.
- _format_error_details: формирование технического блока ошибки.
- _redact_sensitive_data: маскирование секретов в тексте исключения.

"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)[^,\s}\"']+"),
    re.compile(r"(?i)(/keys/)[A-Za-z0-9_-]{12,}"),
)
PROVIDER_STATUS_PATTERNS = (
    re.compile(r"\bresponse_code\s*[=:]\s*(\d{3})\b", re.IGNORECASE),
    re.compile(r"\bGigachatResponseError\s*\(\s*status\s*=\s*(\d{3})\b", re.IGNORECASE),
    re.compile(r'\\?"status\\?"\s*:\s*(\d{3})\b', re.IGNORECASE),
)
NESTED_ERROR_ATTRIBUTES = (
    "data",
    "error",
    "response",
    "result",
    "body",
    "raw_data",
    "__cause__",
    "__context__",
)
STATUS_ATTRIBUTES = ("response_code", "status_code", "status")
MAX_ERROR_OBJECTS_TO_INSPECT = 50
CONNECTION_OR_TIMEOUT_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectionError",
    "ReadError",
    "ReadTimeout",
    "TimeoutError",
    "TimeoutException",
}


def is_retryable_model_error(error: Exception) -> bool:
    """Определяет, следует ли повторить вызов модели.

    Args:
        error: Исключение, возникшее при обращении к модели.

    Returns:
        ``True`` для сетевых ошибок, таймаутов, rate limit и временных HTTP-ошибок
        провайдера; иначе ``False``.
    """

    if _is_connection_or_timeout_error(error):
        return True

    provider_status_code = _extract_provider_status_code(error)
    return (
        provider_status_code is not None
        and _is_retryable_status_code(provider_status_code)
    )


def format_model_error(error: Exception) -> str:
    """Формирует пользовательское сообщение с техническими деталями ошибки.

    Args:
        error: Последнее исключение после завершения повторных попыток.

    Returns:
        Русскоязычное пояснение и очищенный технический блок ошибки.
    """

    if _is_connection_or_timeout_error(error):
        summary = (
            "Не удалось подключиться к модели после нескольких попыток. "
            "Проверьте соединение и повторите запрос позже."
        )
    else:
        status_code = _extract_provider_status_code(error)
        if status_code is None:
            summary = (
                "Не удалось получить ответ модели. Запрос завершён с ошибкой; "
                "попробуйте повторить его позже."
            )
        elif status_code in {401, 403}:
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
    return f"{summary}\n\n{_format_error_details(error)}"


def _is_connection_or_timeout_error(error: Exception) -> bool:
    """Проверяет, похожа ли ошибка на сетевой сбой или timeout.

    Args:
        error: Исключение model call.

    Returns:
        ``True``, если исключение является стандартным ``ConnectionError``/
        ``TimeoutError`` или SDK-классом с типичным именем сетевой ошибки.
    """

    return (
        isinstance(error, (ConnectionError, TimeoutError))
        or type(error).__name__ in CONNECTION_OR_TIMEOUT_ERROR_NAMES
    )


def _extract_provider_status_code(error: Exception) -> int | None:
    """Извлекает фактический код ошибки из исключения или вложенного ответа proxy.

    В корпоративном proxy транспортный HTTP-код может быть равен ``200``, а реальный
    статус модели хранится в ``data.response_code`` или ``data.error.status``.

    Args:
        error: Исключение model call, которое может содержать DTO ответа провайдера.

    Returns:
        Первый найденный код ошибки ``>= 400``; если таких кодов нет, транспортный
        или иной найденный код; ``None``, если статус определить невозможно.
    """

    status_codes = _collect_status_codes(error)
    error_codes = [status_code for status_code in status_codes if status_code >= 400]
    if error_codes:
        return error_codes[0]
    return status_codes[0] if status_codes else None


def _collect_status_codes(root: Any) -> list[int]:
    """Обходит исключение и вложенные DTO, собирая HTTP-подобные статусы.

    Args:
        root: Исключение, mapping, Pydantic DTO или вложенное значение SDK.

    Returns:
        Список найденных трёхзначных кодов в порядке обхода.
    """

    queue: deque[Any] = deque([root])
    visited: set[int] = set()
    status_codes: list[int] = []

    while queue and len(visited) < MAX_ERROR_OBJECTS_TO_INSPECT:
        value = queue.popleft()
        if value is None:
            continue
        if isinstance(value, (str, bytes, bytearray)):
            status_codes.extend(_status_codes_from_text(value))
            continue
        if isinstance(value, (int, float, bool)):
            continue

        value_id = id(value)
        if value_id in visited:
            continue
        visited.add(value_id)

        if isinstance(value, Mapping):
            for key, nested_value in value.items():
                if str(key) in STATUS_ATTRIBUTES:
                    status_code = _normalize_status_code(nested_value)
                    if status_code is not None:
                        status_codes.append(status_code)
                queue.append(nested_value)
            continue

        for attribute_name in STATUS_ATTRIBUTES:
            status_code = _normalize_status_code(
                getattr(value, attribute_name, None)
            )
            if status_code is not None:
                status_codes.append(status_code)

        for attribute_name in NESTED_ERROR_ATTRIBUTES:
            nested_value = getattr(value, attribute_name, None)
            if nested_value is not None:
                queue.append(nested_value)

        if isinstance(value, BaseException):
            queue.extend(value.args)

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                queue.append(model_dump())
            except Exception:
                pass

        queue.append(str(value))

    return status_codes


def _status_codes_from_text(value: str | bytes | bytearray) -> list[int]:
    """Извлекает коды ошибки из текста ответа KitAI/GigaChat.

    Args:
        value: Строка или байты с представлением ответа proxy или исключения.

    Returns:
        Список найденных трёхзначных кодов в порядке шаблонов и появления.
    """

    text = (
        bytes(value).decode("utf-8", errors="replace")
        if isinstance(value, (bytes, bytearray))
        else value
    )
    status_codes: list[int] = []
    for pattern in PROVIDER_STATUS_PATTERNS:
        status_codes.extend(int(match) for match in pattern.findall(text))
    return status_codes


def _normalize_status_code(value: Any) -> int | None:
    """Преобразует значение в корректный трёхзначный статус.

    Args:
        value: Число, строка или произвольное значение атрибута статуса.

    Returns:
        Целый код от ``100`` до ``599`` либо ``None``.
    """

    try:
        status_code = int(value)
    except (TypeError, ValueError):
        return None
    if 100 <= status_code <= 599:
        return status_code
    return None


def _is_retryable_status_code(status_code: int) -> bool:
    """Проверяет, является ли код временной ошибкой провайдера.

    Args:
        status_code: HTTP-подобный код из транспорта или тела ответа.

    Returns:
        ``True`` для timeout, conflict, rate limit и server errors.
    """

    return status_code in {408, 409, 429} or status_code >= 500


def _format_error_details(error: Exception) -> str:
    """Формирует технический блок ошибки для отображения в чате.

    Args:
        error: Исключение провайдера модели.

    Returns:
        Markdown-блок с типом, HTTP-кодом и очищенным текстом исключения.
    """

    lines = [f"- Тип: `{type(error).__name__}`"]
    provider_status_code = _extract_provider_status_code(error)
    if provider_status_code is not None:
        lines.append(f"- Код провайдера: `{provider_status_code}`")
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
