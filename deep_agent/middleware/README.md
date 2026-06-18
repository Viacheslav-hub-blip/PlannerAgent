# Middleware

Project-specific middleware:

- `ToolOutputFileMiddleware` пишет полные табличные результаты в pickle и оставляет в
  контексте компактный preview.
- `ToolContextNoticeMiddleware` добавляет к успешным tool results понятное текстовое
  уведомление, что контекст получен и передан агенту.
- `PostgresLoggingMiddleware` подключается из `deep_agent/logging` и пишет статистику
  user request, tool events и final answer в PostgreSQL, если logging включён.
- `model_errors.py` безопасно форматирует финальные ошибки провайдера.

Retries, tool/model limits, filesystem, memory, HITL, planning и subagents
предоставляются встроенными middleware LangChain и Deep Agents.
