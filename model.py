"""Конфигурация моделей LangChain для локальных запусков агента.

Содержит:
- model: ChatOpenAI-клиент основного агента.
- embeddings: OpenAIEmbeddings-клиент для эмбеддингов.
- gigachat: опциональный GigaChat-клиент для ручных экспериментов.
- _build_optional_gigachat: сборка GigaChat только при наличии credentials в окружении.
- get_answer: простой helper для вызова prompt-template через выбранную модель.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain_gigachat import GigaChat

model = ChatOpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.environ.get("OPENAI_API_KEY"),
    model=os.environ.get("DEEP_AGENT_MODEL", "deepseek/deepseek-v4-flash"),
    temperature=float(os.environ.get("DEEP_AGENT_TEMPERATURE", "0.2")),
    timeout=float(os.environ.get("DEEP_AGENT_TIMEOUT", "120")),
    max_retries=int(os.environ.get("DEEP_AGENT_MAX_RETRIES", "0")),
)

embeddings = OpenAIEmbeddings(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.environ.get("OPENAI_API_KEY"),
    model=os.environ.get("DEEP_AGENT_EMBEDDING_MODEL", "openai/text-embedding-3-small"),
)


def _build_optional_gigachat() -> GigaChat | None:
    """Создаёт GigaChat-клиент при наличии credentials в окружении.

    Returns:
        Настроенный ``GigaChat`` или ``None``, если ``GIGACHAT_CREDENTIALS`` не задан.
    """

    credentials = os.environ.get("GIGACHAT_CREDENTIALS")
    if not credentials:
        return None
    return GigaChat(
        credentials=credentials,
        model=os.environ.get("GIGACHAT_MODEL", "GigaChat-2-Max"),
        verify_ssl_certs=os.environ.get("GIGACHAT_VERIFY_SSL_CERTS", "true").lower()
        not in {"0", "false", "no"},
    )


gigachat = _build_optional_gigachat()


def get_answer(
    prompt: str,
    chat_model: Any,
    prompt_params: dict[str, Any] | None = None,
) -> str:
    """Возвращает текстовый ответ модели на prompt-template.

    Args:
        prompt: Шаблон пользовательского или системного prompt.
        chat_model: LangChain chat model, через которую выполняется запрос.
        prompt_params: Параметры для подстановки в шаблон prompt.

    Returns:
        Строковый ответ модели после применения StrOutputParser.
    """

    if prompt_params is None:
        prompt_params = {}
    chain = ChatPromptTemplate.from_template(prompt) | chat_model | StrOutputParser()
    return chain.invoke(prompt_params)


if __name__ == "__main__":
    if gigachat is None:
        raise RuntimeError("Для ручного запуска задайте GIGACHAT_CREDENTIALS.")
    print(gigachat.invoke("hi"))
