# Deep Agent

Аналитический DeepAgent для GigaChat KitAI. Ядро агента находится в `deep_agent/`
и не зависит от локального UI или LangGraph Agent Server adapter.

## Структура

- `deep_agent/` — core package: сборка агента, state, settings, KitAI model.
- `deep_agent/data_processing/` — схемы, parser и helper-ы `load_data`.
- `deep_agent/execution/` — filesystem backend, Python sandbox, trace, harness profile.
- `deep_agent/tools/` — LangChain tools, которые подключаются к агенту.
- `deep_agent/middleware/` — middleware без внешних provider-интеграций.
- `deep_agent/prompts/` — prompt-модули с явными именами.
- `adapters/` — optional SDK adapters. Сейчас есть LangGraph Agent Server adapter.
- `local_ui/` — launcher/config/frontend локального UI, без Python-инициализации агента.
- `skills/` — доменные навыки и справочники вне Python-пакета.

## Public API

```python
from deep_agent.agent import build_agent
from deep_agent.agent_settings import AgentSettings, load_agent_settings
from deep_agent.gigachat_kitai_model import build_gigachat_kitai_model
from deep_agent.tools.load_data_spark_tool import build_spark_data_tools
```

`build_agent(...)` — основной способ собрать агента без UI. Для LangGraph Agent Server
используется тонкий слой `adapters/langgraph_agent_server.py`, который экспортирует
`agent`.

## Проверка

```powershell
python -m compileall -q deep_agent adapters scripts run_ui.py
python scripts/check_project_quality.py
```

Эти проверки не требуют API-ключей и не вызывают внешнюю модель.
