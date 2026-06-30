# Deep Agent Core

`deep_agent` — ядро агента. Пакет собирает supervisor, subagents, prompts,
middleware, tools и execution backend. UI и LangGraph Agent Server adapter находятся
вне core package.

## Основные файлы

- `agent.py` — `build_agent(...)`, сборка supervisor graph и subagents.
- `agent_settings.py` — Python-defaults и производные пути workspace.
- `agent_state.py` — state schema агента.
- `gigachat_kitai_model.py` — сборка модели GigaChat KitAI.
- `subagents.py` — конфигурации `coding-agent` и `data-retrieval-agent`.

## Папки

- `prompts/` — prompt-модули с суффиксом `prompt`.
- `data_processing/` — модели, parser, нормализация и helper-ы `load_data`.
- `tools/` — LangChain tools.
- `middleware/` — middleware агента.
- `execution/` — filesystem backend, Python sandbox, trace logger, harness profile.

## Границы ответственности

Core запускается напрямую через `build_agent(...)` и не импортирует `local_ui`.
LangGraph Agent Server использует `adapters/langgraph_agent_server.py`; это
интеграционный слой, а не публичный API ядра.
