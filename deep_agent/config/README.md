# Config

`defaults.json` содержит значения по умолчанию. Внешний проект может передать
override через `DEEP_AGENT_CONFIG_PATH`.

Инициализация моделей находится не в `config`, а в `deep_agent/models/instances.py`:
там задаются основная LLM, embeddings, локальная UI-модель и Qwen VLM.

PostgreSQL logging настраивается в `deep_agent/logging/postgres_config.py`. По
умолчанию `POSTGRES_LOGGING_ENABLED = False`; после заполнения DSN можно вызвать
`initialize_postgres_logging()` для создания схемы и таблиц.
