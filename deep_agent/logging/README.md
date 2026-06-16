# Logging

PostgreSQL logging предназначен только для статистики и аудита запусков. Агент не
использует эти данные как память.

Настройка находится в `postgres_config.py`:

- `POSTGRES_LOGGING_ENABLED`;
- `POSTGRES_DSN`;
- `POSTGRES_SCHEMA`;
- `POSTGRES_AGENT_RUNS_TABLE`;
- `POSTGRES_TOOL_EVENTS_TABLE`.

Middleware логирует user request, tool events с параметрами, ошибками и полным выводом,
а также final answer. Prompt-запросы к модели и рассуждения не логируются.
