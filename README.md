# Deep Agent

Гибридный LangChain/DeepAgents агент для аналитики событийных данных и работы с
кодом. Основной пакет называется `deep_agent`.

## Структура

- `deep_agent/` — продуктовый Python-пакет.
- `deep_agent/entrypoints/` — Python entrypoints для UI и validation/demo-запусков.
- `deep_agent/models/` — инициализация LLM, embeddings и VLM.
- `deep_agent/logging/` — конфигурация и middleware PostgreSQL logging.
- `deep_agent/prompts/` — отдельные prompts supervisor, subagents и tools.
- `deep_agent/subagents/` — расширяемые спецификации специализированных агентов.
- `deep_agent/middleware/` — LangChain middleware.
- `deep_agent/tools/` — LangChain tools.
- `deep_agent/integrations/` — подключение внешних сервисов, включая MCP.
- `deep_agent/data/` — схемы и разбор запросов к табличным данным.
- `deep_agent/runtime/` — filesystem, sandbox, tracing и harness.
- `tests/` — unit, integration и validation-инфраструктура.
- `experiments/` и `evals/` — исследовательский код вне продуктового пакета.
- `local_ui/` — launcher/config/frontend-слой локального LangGraph UI без
  project-authored Python entrypoints.

## Проверка

```powershell
python -m pytest -q
python -m compileall -q deep_agent tests scripts run.py run_ui.py model.py
python scripts/check_project_quality.py
```

Проверки не требуют API-ключей. Сетевые и модельные проверки запускаются только
явно пользователем.
