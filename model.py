"""Compatibility shim для конфигурации моделей DeepAgent.

Содержит:
- model: выбранный через окружение chat-клиент основного агента.
- embeddings: OpenAIEmbeddings-клиент для эмбеддингов.
- gigachat: опциональный GigaChat-клиент для ручных экспериментов.
- get_answer: helper для вызова prompt-template через выбранную модель.
"""

from __future__ import annotations

from deep_agent.models.instances import embeddings, get_answer, gigachat, model


if __name__ == "__main__":
    if gigachat is None:
        raise RuntimeError("Для ручного запуска задайте GIGACHAT_CREDENTIALS.")
    print(gigachat.invoke("hi"))
