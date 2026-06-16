"""Клиент визуальной LLM Qwen.

Содержит:
- QwenVLMConfig: параметры подключения к OpenAI-совместимому VLM API.
- encode_image: кодирование локального изображения в base64.
- QwenVLMClient: синхронный и асинхронный клиент анализа изображений.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class QwenVLMConfig:
    """Параметры подключения и ограничения для вызова Qwen VLM.

    Attributes:
        base_url: Базовый URL OpenAI-совместимого VLM API.
        model_name: Имя визуальной модели.
        api_key: API-ключ или техническое значение для локального сервиса.
        timeout: Таймаут запроса в секундах.
        max_tokens: Максимальное число токенов ответа.
    """

    base_url: str
    model_name: str = "Qwen3-VL-8B-Instruct"
    api_key: str = "EMPTY"
    timeout: int = 3600
    max_tokens: int = 4096


def encode_image(image_path: str | Path) -> str:
    """Кодирует локальное изображение в base64 для отправки в VLM API.

    Args:
        image_path: Путь к локальному изображению.

    Returns:
        Base64-строка содержимого файла.
    """

    with Path(image_path).open("rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


class QwenVLMClient:
    """Клиент OpenAI-совместимой визуальной модели Qwen.

    Args:
        config: Параметры подключения к VLM API.
    """

    def __init__(self, config: QwenVLMConfig) -> None:
        """Инициализирует клиент и подготавливает внутреннее API-подключение.

        Args:
            config: Параметры подключения к VLM API.

        Returns:
            ``None``.
        """

        self._config = config
        self._client = self._build_client(config)

    @staticmethod
    def _build_client(config: QwenVLMConfig) -> Any:
        """Создаёт OpenAI-клиент для дальнейших запросов к VLM.

        Args:
            config: Параметры подключения к VLM API.

        Returns:
            Экземпляр ``openai.OpenAI``.

        Raises:
            ImportError: Пакет ``openai`` не установлен.
        """

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "Для работы клиента Qwen VLM требуется пакет openai."
            ) from exc

        return OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
        )

    def generate_from_image(
        self,
        *,
        image_path: str | Path,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> str:
        """Синхронно отправляет изображение в VLM и возвращает текстовый ответ.

        Args:
            image_path: Путь к локальному изображению.
            system_prompt: Системная инструкция для VLM.
            user_prompt: Пользовательский запрос к изображению.
            max_tokens: Опциональный лимит токенов ответа.

        Returns:
            Текстовый ответ VLM.
        """

        base64_image = encode_image(image_path)
        response = self._client.chat.completions.create(
            model=self._config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                        {
                            "type": "text",
                            "text": user_prompt,
                        },
                    ],
                },
            ],
            max_tokens=max_tokens or self._config.max_tokens,
        )
        return response.choices[0].message.content or ""

    async def agenerate_from_image(
        self,
        *,
        image_path: str | Path,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
    ) -> str:
        """Асинхронно отправляет изображение в VLM через thread wrapper.

        Args:
            image_path: Путь к локальному изображению.
            system_prompt: Системная инструкция для VLM.
            user_prompt: Пользовательский запрос к изображению.
            max_tokens: Опциональный лимит токенов ответа.

        Returns:
            Текстовый ответ VLM.
        """

        return await asyncio.to_thread(
            self.generate_from_image,
            image_path=image_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
        )


__all__ = ["QwenVLMClient", "QwenVLMConfig", "encode_image"]
