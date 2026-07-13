# Middleware

Папка содержит project-specific middleware:

- `filesystem_path_middleware.py` — проверка workspace-путей в tool calls.
- `gigachat_runtime_middleware.py` — устойчивость tool loop для GigaChat KitAI.
- `model_error_middleware.py` — retry predicate и безопасное сообщение об ошибке модели.
- `skills_context_middleware.py` — выбор и предзагрузка релевантных skills.
- `todo_reset_middleware.py` — сброс todo state между пользовательскими запросами.
- `tool_context_middleware.py` — короткое уведомление о переданном tool context.
- `tool_description_middleware.py` — prompt-visible описания tools.
- `prompt_logging_middleware.py` — JSON-снимки фактических model requests.
- `request_logging_middleware.py` — опциональная запись human-запросов в PostgreSQL.
- `user_profile_memory_middleware.py` — создание Spark-профиля до чтения memory.

Retries, лимиты tool/model calls, memory и subagents подключаются через штатные
middleware LangChain и Deep Agents.
