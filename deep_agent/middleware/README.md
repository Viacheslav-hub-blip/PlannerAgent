# Middleware

Project-specific код middleware используется для записи полных табличных результатов
в pickle (`ToolOutputFileMiddleware`) и безопасного форматирования финальных ошибок
провайдера (`model_errors.py`).

Skills, retries, tool/model limits, filesystem, memory, HITL, planning и subagents
предоставляются встроенными middleware LangChain и Deep Agents.
