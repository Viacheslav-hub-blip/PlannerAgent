"""Python-конфигурация KitAI-модели для локального LangGraph UI.

Содержит:
- model: единый экземпляр модели для supervisor, subagents и query parser.
"""

from deep_agent.models import DeepAgentsKitaiChatModel

# Замените только значения ниже на параметры целевой закрытой среды.
model = DeepAgentsKitaiChatModel(
    model="GigaChat-2-Max",
    kitai_host_sdk="https://kitai-host.example.internal",
    cert_file="/absolute/path/to/client.crt",
    key_file="/absolute/path/to/client.key",
    verify_ssl=False,
    system_name="lab",
    module_name="lab_antifraud_edge",
    polling_retries=500,
    polling_delay_in_sec=2,
    polling_start_delay_in_sec=2,
    polling_timeout_in_sec=180,
    temperature=0.05,
    profanity_check=False,
    verbose=True,
)
