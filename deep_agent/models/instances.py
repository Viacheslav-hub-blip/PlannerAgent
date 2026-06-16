"""Конфигурация моделей LangChain и VLM для локальных запусков DeepAgent.

Содержит:
- build_main_model: сборка основной chat-модели по переменным окружения.
- build_openai_embeddings: сборка клиента эмбеддингов.
- build_optional_gigachat: сборка GigaChat для ручных экспериментов.
- build_local_ui_model: сборка KitAI-модели для локального UI.
- build_qwen_vlm_config: сборка конфигурации Qwen VLM.
- build_qwen_vlm_client: сборка клиента Qwen VLM.
- get_model_instance: ленивое получение основной chat-модели.
- get_embeddings_instance: ленивое получение embeddings-клиента.
- get_gigachat_instance: ленивое получение опционального GigaChat-клиента.
- get_answer: простой helper для вызова prompt-template через выбранную модель.
- __getattr__: compatibility-доступ к ``model``, ``embeddings`` и ``gigachat``.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_gigachat import GigaChat
from langchain_openai import ChatOpenAI
from langchain_openai.embeddings import OpenAIEmbeddings

from deep_agent.models.kitai import DeepAgentsKitaiChatModel
from deep_agent.models.vlm import QwenVLMClient, QwenVLMConfig


def build_main_model() -> Any:
    """Создаёт основную chat-модель по выбранному провайдеру.

    Returns:
        OpenAI-compatible либо KitAI LangChain chat-модель.

    Raises:
        ValueError: Указан неподдерживаемый ``DEEP_AGENT_MODEL_PROVIDER``.
    """

    provider = os.environ.get("DEEP_AGENT_MODEL_PROVIDER", "openai").strip().lower()
    if provider == "kitai":
        from deep_agent.models import build_kitai_model

        return build_kitai_model()
    if provider != "openai":
        raise ValueError(f"Неподдерживаемый провайдер модели: {provider}")
    return ChatOpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENAI_API_KEY"),
        model=os.environ.get("DEEP_AGENT_MODEL", "deepseek/deepseek-v4-flash"),
        temperature=float(os.environ.get("DEEP_AGENT_TEMPERATURE", "0.2")),
        timeout=float(os.environ.get("DEEP_AGENT_TIMEOUT", "120")),
        max_retries=int(os.environ.get("DEEP_AGENT_MAX_RETRIES", "0")),
    )


def build_openai_embeddings() -> OpenAIEmbeddings:
    """Создаёт OpenAI-compatible клиент эмбеддингов.

    Returns:
        Экземпляр ``OpenAIEmbeddings`` с настройками из окружения.
    """

    return OpenAIEmbeddings(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENAI_API_KEY"),
        model=os.environ.get(
            "DEEP_AGENT_EMBEDDING_MODEL",
            "openai/text-embedding-3-small",
        ),
    )


def build_optional_gigachat() -> GigaChat | None:
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
        verify_ssl_certs=os.environ.get(
            "GIGACHAT_VERIFY_SSL_CERTS",
            "true",
        ).lower()
        not in {"0", "false", "no"},
    )


def build_local_ui_model() -> DeepAgentsKitaiChatModel:
    """Создаёт KitAI-модель для локального LangGraph UI.

    Returns:
        Единый экземпляр модели для supervisor, subagents и query parser UI.
    """

    cert_file_path = "/opt/jupyterhub/client_certs/kitai/cert.pem"
    cert_key_file_path = "/opt/jupyterhub/client_certs/kitai/key.pem"
    return DeepAgentsKitaiChatModel(
        model="GigaChat-3-Ultra",
        kitai_host_sdk="https://hcscr-prom.omega.sbrf.ru",
        cert_file=cert_file_path,
        key_file=cert_key_file_path,
        verify_ssl=False,
        system_name="csp_lab",
        module_name="csp_lab_antifraud_edge",
        polling_retries=500,
        polling_delay_in_sec=2,
        polling_start_delay_in_sec=2,
        polling_timeout_in_sec=180,
        temperature=0.15,
        profanity_check=False,
        verbose=True,
    )


def build_qwen_vlm_config() -> QwenVLMConfig:
    """Создаёт конфигурацию Qwen VLM из Python-констант и окружения.

    Returns:
        Настройки подключения к OpenAI-совместимому VLM API.
    """

    return QwenVLMConfig(
        base_url=os.environ.get("QWEN_VLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        model_name=os.environ.get("QWEN_VLM_MODEL", "Qwen3-VL-8B-Instruct"),
        api_key=os.environ.get("QWEN_VLM_API_KEY", "EMPTY"),
        timeout=int(os.environ.get("QWEN_VLM_TIMEOUT", "3600")),
        max_tokens=int(os.environ.get("QWEN_VLM_MAX_TOKENS", "4096")),
    )


def build_qwen_vlm_client() -> QwenVLMClient:
    """Создаёт клиент Qwen VLM для инструмента анализа изображений.

    Returns:
        Готовый клиент ``QwenVLMClient``.
    """

    return QwenVLMClient(build_qwen_vlm_config())


_MODEL_SINGLETON: Any | None = None
_EMBEDDINGS_SINGLETON: OpenAIEmbeddings | None = None
_GIGACHAT_SINGLETON: GigaChat | None = None
_GIGACHAT_INITIALIZED = False


def get_model_instance() -> Any:
    """Лениво возвращает singleton основной chat-модели.

    Returns:
        Экземпляр основной LangChain chat-модели.
    """

    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        _MODEL_SINGLETON = build_main_model()
    return _MODEL_SINGLETON


def get_embeddings_instance() -> OpenAIEmbeddings:
    """Лениво возвращает singleton клиента embeddings.

    Returns:
        Экземпляр ``OpenAIEmbeddings``.
    """

    global _EMBEDDINGS_SINGLETON
    if _EMBEDDINGS_SINGLETON is None:
        _EMBEDDINGS_SINGLETON = build_openai_embeddings()
    return _EMBEDDINGS_SINGLETON


def get_gigachat_instance() -> GigaChat | None:
    """Лениво возвращает singleton опционального GigaChat-клиента.

    Returns:
        ``GigaChat`` или ``None``, если credentials не заданы.
    """

    global _GIGACHAT_INITIALIZED, _GIGACHAT_SINGLETON
    if not _GIGACHAT_INITIALIZED:
        _GIGACHAT_SINGLETON = build_optional_gigachat()
        _GIGACHAT_INITIALIZED = True
    return _GIGACHAT_SINGLETON


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


def __getattr__(name: str) -> Any:
    """Лениво предоставляет старые module attributes для compatibility imports.

    Args:
        name: Имя запрошенного атрибута модуля.

    Returns:
        Значение ``model``, ``embeddings`` или ``gigachat``.

    Raises:
        AttributeError: Атрибут не поддерживается этим модулем.
    """

    if name == "model":
        return get_model_instance()
    if name == "embeddings":
        return get_embeddings_instance()
    if name == "gigachat":
        return get_gigachat_instance()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "build_local_ui_model",
    "build_main_model",
    "build_openai_embeddings",
    "build_optional_gigachat",
    "build_qwen_vlm_client",
    "build_qwen_vlm_config",
    "embeddings",
    "get_answer",
    "get_embeddings_instance",
    "get_gigachat_instance",
    "get_model_instance",
    "gigachat",
    "model",
]
