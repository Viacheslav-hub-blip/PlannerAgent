"""Адаптер корпоративной KitAI-модели для сообщений LangChain и DeepAgents.

Содержит:
- DeepAgentsKitaiChatModel: KitAI-модель с нормализацией сообщений DeepAgents.
- content_to_text: преобразование content blocks в строку.
- normalize_kitai_message: создание совместимой копии сообщения LangChain.
- normalize_kitai_messages: нормализация одного сообщения или списка сообщений.
- build_gigachat_kitai_model: сборка Gigachat KitAI chat-модели из явных параметров.
- _require_text_parameter: проверка обязательного текстового параметра.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage

try:
    from sber_kitai_sdk_langchain.system_chat_model import KitaiSystemChatModel
    from sber_kitai_sdk_py.generated.api_client import ApiClient
    from sber_kitai_sdk_py.generated.configuration import Configuration
except ImportError:
    KitaiSystemChatModel = None  # type: ignore[assignment]
    ApiClient = None  # type: ignore[assignment]
    Configuration = None  # type: ignore[assignment]


def content_to_text(content: Any) -> str:
    """Преобразует содержимое сообщения LangChain в строку для KitAI.

    Args:
        content: Строка, content block, список блоков или произвольное значение.

    Returns:
        Строковое представление содержимого сообщения.
    """

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text") or "")
        return json.dumps(content, ensure_ascii=False, default=str)
    return str(content)


def normalize_kitai_message(message: BaseMessage) -> BaseMessage:
    """Создаёт копию сообщения, совместимую с ограничениями KitAI SDK.

    Args:
        message: Исходное сообщение LangChain с текстовым или блочным content.

    Returns:
        Сообщение исходного типа с непустым строковым content и сохранёнными metadata.
    """

    content = content_to_text(message.content)
    if not content.strip():
        role = getattr(message, "type", type(message).__name__)
        content = f"[{role} message has no text content]"

    update: dict[str, Any] = {"content": content}
    if getattr(message, "type", None) == "ai":
        additional_kwargs = dict(message.additional_kwargs or {})
        additional_kwargs.setdefault(
            "functions_state_id",
            getattr(message, "functions_state_id", None),
        )
        update["additional_kwargs"] = additional_kwargs
    return message.model_copy(update=update)


def normalize_kitai_messages(input_value: Any) -> Any:
    """Нормализует сообщения перед передачей в KitAI SDK.

    Args:
        input_value: Одно сообщение LangChain, список сообщений или другое значение.

    Returns:
        Нормализованное сообщение, список сообщений либо исходное значение.
    """

    if isinstance(input_value, BaseMessage):
        return normalize_kitai_message(input_value)
    if isinstance(input_value, list) and all(
        isinstance(item, BaseMessage) for item in input_value
    ):
        return [normalize_kitai_message(item) for item in input_value]
    return input_value


class DeepAgentsKitaiChatModel(
    KitaiSystemChatModel if KitaiSystemChatModel is not None else object
):
    """KitAI-модель с нормализацией content blocks LangChain.

    Args:
        model: Имя модели в KitAI.
        kitai_host_sdk: URL корпоративного KitAI API.
        cert_file: Абсолютный путь к клиентскому сертификату.
        key_file: Абсолютный путь к закрытому ключу сертификата.
        verify_ssl: Проверять TLS-сертификат сервера.
        system_name: Имя системы KitAI.
        module_name: Имя модуля KitAI.
        polling_retries: Максимальное число проверок готовности ответа.
        polling_delay_in_sec: Интервал между проверками ответа.
        polling_start_delay_in_sec: Задержка перед первой проверкой ответа.
        polling_timeout_in_sec: Общий таймаут ожидания ответа.
        temperature: Температура генерации.
        profanity_check: Использовать встроенную проверку контента.
        verbose: Включить подробный режим SDK.
        **kwargs: Дополнительные параметры ``KitaiSystemChatModel``.
    """

    def __init__(
        self,
        *,
        model: str,
        kitai_host_sdk: str,
        cert_file: str,
        key_file: str,
        verify_ssl: bool = False,
        system_name: str = "lab",
        module_name: str = "lab_antifraud_edge",
        polling_retries: int = 500,
        polling_delay_in_sec: int = 2,
        polling_start_delay_in_sec: int = 2,
        polling_timeout_in_sec: int = 180,
        temperature: float = 0.05,
        profanity_check: bool = False,
        verbose: bool = True,
        **kwargs: Any,
    ) -> None:
        """Инициализирует KitAI API client и LangChain chat-модель.

        Args:
            model: Имя модели в KitAI.
            kitai_host_sdk: URL корпоративного KitAI API.
            cert_file: Абсолютный путь к клиентскому сертификату.
            key_file: Абсолютный путь к закрытому ключу сертификата.
            verify_ssl: Проверять TLS-сертификат сервера.
            system_name: Имя системы KitAI.
            module_name: Имя модуля KitAI.
            polling_retries: Максимальное число проверок готовности ответа.
            polling_delay_in_sec: Интервал между проверками ответа.
            polling_start_delay_in_sec: Задержка перед первой проверкой ответа.
            polling_timeout_in_sec: Общий таймаут ожидания ответа.
            temperature: Температура генерации.
            profanity_check: Использовать встроенную проверку контента.
            verbose: Включить подробный режим SDK.
            **kwargs: Дополнительные параметры базовой модели.

        Returns:
            ``None``.

        Raises:
            RuntimeError: Корпоративные KitAI SDK не установлены.
        """

        if Configuration is None or ApiClient is None or KitaiSystemChatModel is None:
            raise RuntimeError(
                "Установите sber_kitai_sdk_langchain и sber_kitai_sdk_py."
            )

        configuration = Configuration(host=kitai_host_sdk)
        configuration.cert_file = cert_file
        configuration.key_file = key_file
        configuration.verify_ssl = verify_ssl

        super().__init__(
            api_client=ApiClient(configuration),
            system_name=system_name,
            module_name=module_name,
            model_name=model,
            polling_retries=polling_retries,
            polling_delay_in_sec=polling_delay_in_sec,
            polling_start_delay_in_sec=polling_start_delay_in_sec,
            polling_timeout_in_sec=polling_timeout_in_sec,
            temperature=temperature,
            profanity_check=profanity_check,
            verbose=verbose,
            **kwargs,
        )

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Выполняет вызов KitAI с нормализованными сообщениями.

        Args:
            messages: Список сообщений LangChain.
            stop: Последовательности остановки генерации.
            run_manager: Менеджер callbacks LangChain.
            **kwargs: Дополнительные параметры вызова модели.

        Returns:
            Результат базового ``KitaiSystemChatModel._generate``.
        """

        return super()._generate(
            normalize_kitai_messages(messages),
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def build_gigachat_kitai_model(
    *,
    kitai_host_sdk: str,
    cert_file: str,
    key_file: str,
    model: str = "GigaChat-2-Max",
    verify_ssl: bool = False,
    system_name: str = "lab",
    module_name: str = "lab_antifraud_edge",
    polling_retries: int = 500,
    polling_delay_in_sec: int = 2,
    polling_start_delay_in_sec: int = 2,
    polling_timeout_in_sec: int = 180,
    temperature: float = 0.05,
    profanity_check: bool = False,
    verbose: bool = True,
) -> Any:
    """Создаёт Gigachat KitAI chat-модель из явно переданных параметров.

    Args:
        kitai_host_sdk: URL корпоративного KitAI API.
        cert_file: Абсолютный путь к клиентскому сертификату.
        key_file: Абсолютный путь к закрытому ключу сертификата.
        model: Имя модели в KitAI.
        verify_ssl: Проверять TLS-сертификат сервера.
        system_name: Имя системы KitAI.
        module_name: Имя модуля KitAI.
        polling_retries: Максимальное число проверок готовности ответа.
        polling_delay_in_sec: Интервал между проверками ответа.
        polling_start_delay_in_sec: Задержка перед первой проверкой ответа.
        polling_timeout_in_sec: Общий таймаут ожидания ответа.
        temperature: Температура генерации.
        profanity_check: Использовать встроенную проверку контента.
        verbose: Включить подробный режим SDK.

    Returns:
        Экземпляр ``KitaiSystemChatModel``, принимающий content blocks LangChain.

    Raises:
        RuntimeError: Корпоративные KitAI SDK не установлены в окружении.
        ValueError: Не переданы обязательные параметры подключения KitAI.
    """

    _require_text_parameter("kitai_host_sdk", kitai_host_sdk)
    _require_text_parameter("cert_file", cert_file)
    _require_text_parameter("key_file", key_file)
    return DeepAgentsKitaiChatModel(
        model=model,
        kitai_host_sdk=kitai_host_sdk,
        cert_file=cert_file,
        key_file=key_file,
        verify_ssl=verify_ssl,
        system_name=system_name,
        module_name=module_name,
        polling_retries=polling_retries,
        polling_delay_in_sec=polling_delay_in_sec,
        polling_start_delay_in_sec=polling_start_delay_in_sec,
        polling_timeout_in_sec=polling_timeout_in_sec,
        temperature=temperature,
        profanity_check=profanity_check,
        verbose=verbose,
    )


def _require_text_parameter(name: str, value: str) -> None:
    """Проверяет, что обязательный текстовый параметр задан.

    Args:
        name: Имя параметра для сообщения об ошибке.
        value: Значение параметра.

    Returns:
        ``None``.

    Raises:
        ValueError: Значение пустое или состоит только из пробелов.
    """

    if not value or not value.strip():
        raise ValueError(f"Параметр {name} должен быть передан явно.")


__all__ = [
    "DeepAgentsKitaiChatModel",
    "build_gigachat_kitai_model",
    "content_to_text",
    "normalize_kitai_message",
    "normalize_kitai_messages",
]
