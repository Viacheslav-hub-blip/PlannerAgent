# Native Analytics DeepAgent

Slim-реализация аналитического DeepAgent на LangChain/DeepAgents: базовый supervisor со всеми встроенными tools, два middleware и subagent для чтения данных.

## Структура

- `analytics_deep_agent.py` — сборка supervisor, subagent, skills backend и permissions.
- `agent_specs.py` — спецификация `data-retrieval-agent`.
- `agent_state.py` — state для skills middleware.
- `skills_context_middleware.py` — LLM-выбор и preload skills по запросу пользователя.
- `tool_output_file_middleware.py` — сохранение больших tabular tool outputs в `.pkl`.
- `python_sandbox.py` — persistent sandbox с helpers `read_pickle_file`, `rows_to_dataframe`.
- `execute_python_code_tool.py` — генерация и выполнение Python-кода с подробным JSON-ответом и traceback при ошибках.
- `prompts.py` — system prompts supervisor и subagent, описание `read_table`.
- `settings.py` и `config/defaults.json` — типизированная загрузка настроек.
- `run_native_analytics_chat.py` — интерактивный терминальный чат на тестовых CSV.
- `skills/` — domain skills (`SKILL.md`), доступные через `/skills/`.
- `data/` — тестовые CSV: `hits`, `cards_event`, `uko_event`.

## Архитектура

Supervisor (`create_deep_agent`):

- встроенные DeepAgents tools: `write_todos`, filesystem, `task`, и др.;
- custom tool `execute_python_code` для расчетов и чтения `.pkl`;
- middleware: `PreloadedSkillsContextMiddleware`, `ToolOutputFileMiddleware`;
- subagent `data-retrieval-agent` с `read_table` и теми же двумя middleware.

Skills backend: `CompositeBackend` с read-only `/skills/**`.

## Запуск чата

Пример использует тестовые CSV из `deep_agent_test/data` через `examples.fake_spark_tools`.
Модель берётся из корневого `model.py`. Для запуска нужны API-ключи.

```powershell
uv run --extra deep-agent-test python deep_agent_test/run_native_analytics_chat.py
```

По умолчанию `main()` выполняет один `invoke` с demo-запросом и печатает все сообщения
(`[Tool call]`, `[Tool result]`, текст агента) после завершения graph.

Интерактивный чат: вызовите `run_chat()` из Python или измените `DEFAULT_DEMO_QUERY` в `main()`.

В консоли печатаются вызовы tools и их результаты в читаемом виде:
`[Tool call]`, `[Tool result]`, preview строк, traceback для `execute_python_code`.

Альтернативный конфиг:

```powershell
$env:DEEP_AGENT_CONFIG_PATH="C:\path\to\deep_agent_config.json"
uv run --extra deep-agent-test python deep_agent_test/run_native_analytics_chat.py
```

## Конфигурация

Основной конфиг: `deep_agent_test/config/defaults.json`.

| Ключ | Назначение |
|---|---|
| `thread_id` | thread id LangGraph для чата |
| `skills_virtual_dir` | виртуальный путь skills в backend |
| `skills_root` | локальная папка skills |
| `data_tools_factory` | import path фабрики production tools (может быть `null`) |
| `data_tools_factory_kwargs` | kwargs для фабрики |
| `tool_outputs_dir` | папка для `.pkl` с большими tool outputs |
| `max_chars_per_skill` | лимит символов одного skill в preload context |
| `tool_output_min_rows_to_save` | порог строк (>10 сохраняет) |
| `tool_output_min_content_chars_to_save` | порог символов content (>60000 сохраняет) |
| `tool_output_preview_rows` | число строк preview в summary |
| `tool_output_inline_original_chars` | лимит дублирования исходного content |

Чат-runner делает один native `agent.invoke()` на сообщение пользователя и печатает
новые сообщения из state (`[Tool call]`, `[Tool result]`, текст агента). Без
автопродолжения и эвристик остановки — поведение определяет LangGraph/DeepAgents.

## Middleware

### Skills preload

1. Строит Skills Index из всех `SKILL.md`.
2. LLM выбирает релевантные skills по user query.
3. Preload выбранных skills в state и system prompt.

### Tool output spill

Если tabular result имеет **>10 строк** или **>60000 символов** content:

- сохраняет `list[dict]` в `.pkl` под `tool_outputs_dir`;
- возвращает агенту имя файла, путь, preview и инструкцию вызвать `execute_python_code`.

### execute_python_code

Persistent sandbox между вызовами в одной сессии. Helpers:

- `read_pickle_file(path)`, `describe_pickle_file(path)`, `rows_to_dataframe(rows)`
- `PROJECT_ROOT`, `TOOL_OUTPUTS_DIR`, `pd`, `np`

При ошибке tool возвращает JSON с полями:

- `error`, `traceback`, `execution_output`
- `possible_causes`, `solution_options`, `retry_guidance`
- `available_variables`, `sandbox_helpers`, `readable_roots`

## Production data tools

```python
from deep_agent_test import build_analytics_deep_agent, load_deep_agent_settings
from model import model

settings = load_deep_agent_settings()
agent = build_analytics_deep_agent(model, settings=settings, data_tools=your_tools)
```

## Проверка синтаксиса

```powershell
python -m py_compile deep_agent_test/analytics_deep_agent.py `
  deep_agent_test/agent_specs.py `
  deep_agent_test/agent_state.py `
  deep_agent_test/prompts.py `
  deep_agent_test/run_native_analytics_chat.py `
  deep_agent_test/settings.py `
  deep_agent_test/skills_context_middleware.py `
  deep_agent_test/tool_output_file_middleware.py
```
