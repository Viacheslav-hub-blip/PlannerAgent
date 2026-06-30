# Middleware

Папка содержит project-specific middleware:

- `filesystem_path_middleware.py` — проверка workspace-путей в tool calls.
- `gigachat_runtime_middleware.py` — устойчивость tool loop для GigaChat KitAI.
- `model_error_middleware.py` — retry predicate и безопасное сообщение об ошибке модели.
- `skills_context_middleware.py` — выбор и предзагрузка релевантных skills.
- `todo_reset_middleware.py` — сброс todo state между пользовательскими запросами.
- `tool_context_middleware.py` — короткое уведомление о переданном tool context.
- `tool_description_middleware.py` — prompt-visible описания tools.
- `tool_output_file_middleware.py` — сохранение крупных tool results в artifacts.

Retries, лимиты tool/model calls, memory и subagents подключаются через штатные
middleware LangChain и Deep Agents.
