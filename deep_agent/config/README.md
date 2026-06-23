# Config

`defaults.json` содержит значения по умолчанию. Внешний проект обычно задаёт
только `workspace_root` через override в `DEEP_AGENT_CONFIG_PATH`; остальные
файловые пути строятся от него в `deep_agent.settings`.

Производные пути по умолчанию:

- `AGENTS.md` для project memory;
- `deep_agent/skills` для skills агента;
- `artifacts` для session artifacts, пользовательских файлов, промежуточных файлов и trace-файлов.

Старые ключи `agents_file_name`, `skills_root`, `tool_outputs_dir` и
`trace_log_dir` всё ещё принимаются как совместимый override, но не нужны в
базовом config.

Инициализация моделей находится не в `config`, а в `deep_agent/models/instances.py`:
там задаются основная LLM, embeddings, локальная UI-модель и Qwen VLM.

PostgreSQL logging настраивается в `deep_agent/logging/postgres_config.py`. По
умолчанию `POSTGRES_LOGGING_ENABLED = False`; после заполнения DSN можно вызвать
`initialize_postgres_logging()` для создания схемы и таблиц.
