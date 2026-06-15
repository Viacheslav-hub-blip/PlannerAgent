"""Адаптер корпоративной KitAI-модели для сообщений LangChain и DeepAgents.

Содержит:
- content_to_text: преобразование content blocks в строку.
- normalize_kitai_message: создание совместимой копии сообщения LangChain.
- normalize_kitai_messages: нормализация одного сообщения или списка сообщений.
- build_kitai_model: сборка KitAI chat-модели из переменных окружения.
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import BaseMessage


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


def build_kitai_model() -> Any:
    """Создаёт KitAI chat-модель с нормализацией сообщений DeepAgents.

    Returns:
        Экземпляр ``KitaiSystemChatModel``, принимающий content blocks LangChain.

    Raises:
        RuntimeError: Корпоративные KitAI SDK не установлены в окружении.
        KeyError: Не задана обязательная переменная окружения KitAI.
    """

    try:
        from sber_kitai_sdk_langchain.system_chat_model import KitaiSystemChatModel
        from sber_kitai_sdk_py.generated.api_client import ApiClient
        from sber_kitai_sdk_py.generated.configuration import Configuration
    except ImportError as error:
        raise RuntimeError(
            "Для DEEP_AGENT_MODEL_PROVIDER=kitai установите "
            "sber_kitai_sdk_langchain и sber_kitai_sdk_py."
        ) from error

    class NormalizedKitaiSystemChatModel(KitaiSystemChatModel):
        """KitAI-модель, преобразующая content blocks LangChain в строки."""

        def _generate(
            self,
            messages: Any,
            stop: Any = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> Any:
            """Выполняет синхронный вызов KitAI с нормализованными сообщениями.

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

    configuration = Configuration(host=os.environ["KITAI_HOST_SDK"])
    configuration.cert_file = os.environ["KITAI_CERT_FILE_PATH"]
    configuration.key_file = os.environ["KITAI_CERT_KEY_FILE_PATH"]
    configuration.verify_ssl = _environment_flag("KITAI_VERIFY_SSL", default=False)

    return NormalizedKitaiSystemChatModel(
        api_client=ApiClient(configuration),
        system_name=os.environ.get("KITAI_SYSTEM_NAME", "lab"),
        module_name=os.environ.get("KITAI_MODULE_NAME", "lab_antifraud_edge"),
        model_name=os.environ.get("DEEP_AGENT_MODEL", "GigaChat-2-Max"),
        polling_retries=int(os.environ.get("KITAI_POLLING_RETRIES", "500")),
        polling_delay_in_sec=int(os.environ.get("KITAI_POLLING_DELAY_SECONDS", "2")),
        polling_start_delay_in_sec=int(
            os.environ.get("KITAI_POLLING_START_DELAY_SECONDS", "2")
        ),
        polling_timeout_in_sec=int(
            os.environ.get("KITAI_POLLING_TIMEOUT_SECONDS", "180")
        ),
        temperature=float(os.environ.get("DEEP_AGENT_TEMPERATURE", "0.05")),
        profanity_check=_environment_flag("KITAI_PROFANITY_CHECK", default=False),
        verbose=_environment_flag("KITAI_VERBOSE", default=True),
    )


def _environment_flag(name: str, *, default: bool) -> bool:
    """Читает булеву переменную окружения.

    Args:
        name: Имя переменной окружения.
        default: Значение при отсутствии переменной.

    Returns:
        Нормализованное булево значение.
    """

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "build_kitai_model",
    "content_to_text",
    "normalize_kitai_message",
    "normalize_kitai_messages",
]
