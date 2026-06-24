# Аналитический coding-agent

Этот пакет содержит готовую надстройку над базовым `deepagents`. Цель пакета простая:
сохранить возможности coding harness, добавить доменные инструкции и безопасные
инструменты аналитики, а также дать понятную точку запуска в других проектах.

Для локальной проверки пакет содержит fake `load_data`, который читает CSV из папки
`data`. Production-запуск использует Spark tool или фабрику из `data_tools_factory`.

## Что добавлено к базовому DeepAgent

Базовый `deepagents` уже умеет вызывать инструменты, запускать subagent-ов, читать файлы
и вести список задач. В этом проекте поверх него добавлены конкретные вещи для
аналитики таблиц и работы с кодом.

1. Workspace и coding capability.

   При инициализации задаётся `workspace_root`. Supervisor и специализированные
   subagents работают с полными путями от настроенного workspace root и видят
   filesystem/terminal tools без дополнительного tool-gating.

2. Project memory и память диалога.

   Корневой `AGENTS.md` загружается штатным `MemoryMiddleware`. История сообщений,
   планы и state сохраняются через LangGraph `InMemorySaver`; повторный вызов с тем же
   `thread_id` продолжает текущий диалог в пределах процесса.

3. Полный filesystem-доступ без HITL.

   `write_file` и `edit_file` выполняются сразу через backend без `permissions=` и
   `interrupt_on`. После записи проектный middleware делает проверочное чтение и
   возвращает ошибку, если файл не подтвержден на диске.

4. Нативные skills.

   Встроенный `SkillsMiddleware` Deep Agents индексирует frontmatter файлов `SKILL.md`.
   Агент видит краткие описания и читает полный `SKILL.md` через `read_file` только при
   совпадении с задачей. Полные справочники полей остаются в `fields.md`/`joins.md` и
   загружаются по необходимости.

5. Специализированные subagents.

   Основной агент не читает таблицы напрямую. Для чтения данных он вызывает
   `data-retrieval-agent`. Этот subagent получает задачу, вызывает `load_data` и
   возвращает supervisor-у короткий структурированный отчет. Для ограниченных coding-задач
   доступен отдельный `coding-agent`, а штатный `general-purpose` сохраняется для общих
   независимых многошаговых задач.

6. Инструменты чтения данных.

   `build_spark_data_tools(spark, query_parser_model=model)` создает production
   `load_data` поверх Spark session. `build_fake_spark_data_tools(query_parser_model=model)`
   создает совместимый локальный tool поверх CSV. Оба принимают один аргумент `query`
   с SQL-подобным запросом.

7. Прозрачный ответ `load_data`.

   Обертка над data-tools добавляет к результату реальный PySpark-код выполненного запроса,
   исходный SQL-подобный запрос, поля, таблицу и примененные фильтры. Это снижает риск,
   что агент перепутает пример строк с полным результатом.

8. Offload больших таблиц.

   Если tool возвращает много строк или слишком большой текст, результат сохраняется в
   pickle в `artifacts`. В контекст агента попадает короткое описание,
   путь к файлу и preview. Полный файл можно читать через `python`.

9. Полный Python runtime.

   Tool `python` нужен для REPL-расчетов по выгруженным данным, чтения pickle,
   join, фильтрации, подготовки итоговых таблиц, файловых операций и subprocess-задач
   внутри настроенного workspace. Tool сохраняет переменные между вызовами, маппит
   полные workspace-пути на фактический корень текущего запуска и регистрирует
   артефакты обычным Python-кодом в `ARTIFACTS_DIR`.

10. Встроенные ограничения выполнения.

   `ToolCallLimitMiddleware` ограничивает общий бюджет tools на запуск,
   `ModelCallLimitMiddleware` — число ходов subagent, а `ModelRetryMiddleware`
   выполняет повторы model calls. После исчерпания повторов backend возвращает
   очищенное AI-сообщение, которое UI показывает без утечки API-ключей.

11. Внутренняя структура агента по запросу.

   `AGENTS.md` содержит только ручные project instructions. Краткую карту внутренних
   файлов агента и путь к папке skills агент получает через
   `get_project_structure(max_entries)`, поэтому системный контекст не раздувается
   корневыми документами, tests, scripts и содержимым отдельных skills.

12. VLM и MCP tools.

   Tool `analyze_image(image_path, query)` анализирует локальное изображение через
   Qwen VLM. Настройки клиента находятся в `deep_agent/models/instances.py`, клиентская
   механика — в `deep_agent/models/vlm.py`. MCP tools загружаются через
   `deep_agent/integrations/mcp.py`; если сервис недоступен, UI entrypoint пишет warning и
   стартует без них.

13. PostgreSQL logging для статистики.

   `PostgresLoggingMiddleware` логирует user request, tool start/end/error с параметрами
   и полным текстом результата, а также final answer. Prompt-запросы и рассуждения не
   логируются. По умолчанию logging выключен в
   `deep_agent/logging/postgres_config.py`.

## Структура пакета

```text
deep_agent/
  agent.py                 # сборка supervisor graph и middleware
  settings.py              # конфигурация
  state.py                 # LangChain AgentState
  entrypoints/             # local UI и validation/demo entrypoints
  models/                  # LLM, embeddings и VLM clients
  logging/                 # PostgreSQL logging config и middleware
  prompts/                 # отдельные prompts по ролям
  subagents/               # отдельный модуль на каждый subagent
  middleware/              # LangChain middleware
  tools/                   # реализации LangChain tools
  integrations/            # внешние подключения, включая MCP
  data/                    # schema, parser и нормализация запросов
  runtime/                 # filesystem, Python runtime, harness и tracing
  config/                  # настройки по умолчанию
  skills/                  # domain skills и справочники
```
Trace-логгер можно подключить как LangChain callback; он пишет подробный txt-файл по
каждому запросу к LLM.

## Локальная проверка

Корневой `run.py` использует CSV из папки `data`:

```bash
python run.py
```

Запуск вызывает настроенную модель для работы агента и разбора `query`. Сам fake tool
не использует Spark и выполняет выборки через pandas.

## Автоматическая тестовая корзина

Валидатору достаточно запустить файл без аргументов:

```bash
python tests/evaluation/run_validation_suite.py
```

При старте файл сам синхронизирует константы `USER_MESSAGE_N` из `run.py` с
`tests/evaluation/validation_cases.json` и `tests/evaluation/VALIDATION_CASES.md`.
Дополнительные параметры командной строки не используются.

Каждый кейс выполняется в отдельном процессе. Таймаут или ошибка одного кейса
не останавливают остальные. После завершения stdout содержит только две строки:

```text
Tool correctness: XX.XX%
Correct answers: XX.XX%
```

Подробная диагностика сохраняется по фиксированному пути
`runs/validation_report.json`. Команда одинакова для Windows и Linux: раннер
использует текущий интерпретатор из `sys.executable` и `pathlib` для путей.
При таймауте завершается вся группа процессов кейса, включая дочерние процессы.

Корзина выполняется асинхронно. Поле `max_concurrency` в
`tests/evaluation/validation_cases.json` ограничивает число одновременно работающих
агентов; значение по умолчанию равно `10`. Progress bar обновляется по мере
завершения кейсов, а результаты в отчете сохраняются в исходном порядке.

В `answer_patterns` задаются обязательные regex для свободного финального текста.
В `tool_expectations` задаются имя инструмента и обязательные regex его аргументов.
Все регулярные выражения проверяются без учета регистра и не требуют строгого JSON
в ответе модели.

## Минимальный запуск со Spark

```python
from pyspark.sql import SparkSession

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.settings import load_deep_agent_settings
from deep_agent.runtime.tracing import FileTraceCallbackHandler, build_trace_file_path
from deep_agent.tools.spark_data import build_spark_data_tools
from model import model

USER_MESSAGE = "текст запроса пользователя"

settings = load_deep_agent_settings()
spark = SparkSession.builder.appName("analytics-deep-agent").getOrCreate()
data_tools = build_spark_data_tools(spark, query_parser_model=model)
agent = build_analytics_deep_agent(
    model=model,
    settings=settings,
    data_tools=data_tools,
    extra_tools=None,
    workspace_root="C:/projects/current-project",
)
trace_file_path = build_trace_file_path(settings.trace_log_dir)
trace_handler = FileTraceCallbackHandler(trace_file_path)
result = agent.invoke(
    {"messages": [{"role": "user", "content": USER_MESSAGE}]},
    config={
        "callbacks": [trace_handler],
        "configurable": {"thread_id": settings.thread_id},
        "recursion_limit": settings.graph_recursion_limit,
    },
)
print(f"Trace log: {trace_file_path}")
```

Если вызов остановился на `write_file` или `edit_file`, продолжите тот же `thread_id`
через LangGraph `Command`:

```python
from langgraph.types import Command

result = agent.invoke(
    Command(resume={"decisions": [{"type": "approve"}]}),
    config={
        "configurable": {"thread_id": settings.thread_id},
        "recursion_limit": settings.graph_recursion_limit,
    },
)
```

Для отклонения передайте `{"type": "reject", "message": "причина"}`. Для изменения
tool call используйте решение `edit` с `edited_action`.

Для другого источника передайте собственный `BaseTool` с именем `load_data` и схемой
аргументов, совместимой с prompt-контрактом.

## Конфигурация

Основной конфиг лежит здесь:

```text
deep_agent/config/defaults.json
```

Главные параметры:

- `workspace_root` - корень coding workspace и рабочая директория terminal.
- Остальные файловые пути строятся от `workspace_root` в коде:
  `AGENTS.md`, `deep_agent/skills`, `artifacts`.
- `agents_file_name`, `skills_root`, `tool_outputs_dir`, `trace_log_dir` можно
  передать в override-конфиге для совместимости, но базовый config их не требует.
- `terminal_timeout` - timeout terminal-команды.
- `terminal_max_output_bytes` - предел возвращаемого terminal output.
- terminal всегда получает только allowlist системных переменных; API-ключи и другие
  переменные пользовательского environment в subprocess не передаются.
- filesystem tools используют виртуальный путь относительно корня workspace: например,
  `/deep_agent/skills/x/SKILL.md` соответствует
  `workspace_root/deep_agent/skills/x/SKILL.md`.
- `/` соответствует пользовательскому `workspace_root` и является базовой областью
  для новых пользовательских файлов и артефактов. `/deep_agent/` — папка реализации
  агента; ее читают и меняют только для задач по коду, prompts, tests или skills агента.
- aliases `/skills`, `/tool_outputs` и `/project_memory` не используются.
- `harness_profile_key` - provider или `provider:model` для регистрации HarnessProfile.
- `tool_output_min_rows_to_save` - после какого числа строк сохранять результат в файл.
- `context_edit_trigger_tokens` - когда чистить старые tool results из контекста.
- `max_model_retries` - число повторов model call через `ModelRetryMiddleware`.
- `read_file_default_limit` - число строк, которое `read_file` читает по умолчанию без явного `limit`.
- `max_tool_calls_per_run` - общий бюджет tool calls одного запуска.
- `max_subagent_model_calls` - лимит шагов модели внутри data-retrieval-agent.

Модели настраиваются в `deep_agent/models/instances.py`. Для локального UI используйте
`build_local_ui_model()`, для VLM — `build_qwen_vlm_config()` и
`build_qwen_vlm_client()`.

PostgreSQL logging настраивается в `deep_agent/logging/postgres_config.py`:

- `POSTGRES_LOGGING_ENABLED` - включает logging middleware;
- `POSTGRES_DSN` - строка подключения;
- `POSTGRES_SCHEMA` - схема для таблиц;
- `POSTGRES_AGENT_RUNS_TABLE` и `POSTGRES_TOOL_EVENTS_TABLE` - имена таблиц.

Функция `initialize_postgres_logging()` создаёт схему и таблицы. Эти логи не
используются агентом как память или источник восстановления состояния.

Если нужен отдельный конфиг для другого проекта, укажите путь в переменной окружения
`DEEP_AGENT_CONFIG_PATH`. Значения из этого файла переопределят defaults.

Локальный `LocalShellBackend` выполняет команды из workspace и не передаёт API-ключи
из пользовательского окружения. Агент может использовать terminal для диагностики,
проверок, сборки и локальных операций внутри configured workspace.

## Trace-лог

Каждый вызов модели записывается отдельным блоком `LLM REQUEST #N`. В начале блока
есть сводка:

- `messages_count` и `tools_count` - сколько сообщений и tools ушло в этот запрос;
- `messages_chars`, `tools_chars` и `total_tokens_estimate` - грубая оценка объема
  контекста;
- `messages_table` - таблица всех сообщений с ролью, классом, размером и числом
  tool calls.

После сводки идут секции `LLM REQUEST #N TOOLS` и `LLM REQUEST #N MESSAGE #M`.
Они содержат полный набор tools и полный content каждого сообщения, которое попало
в конкретный запрос к LLM.

## Формат `load_data`

`load_data` принимает один параметр `query`. Внутри `query` передается SQL-подобный
запрос. Для каждой выборки обязателен `PERIOD`; `SELECT *` и `SELECT all` запрещены.

Пример обычной выборки:

```text
query:
LOAD uko
PERIOD event_dt FROM '20260123' TO '20260124'
SELECT event_id, event_dt, event_dttm_readable, epk_id, event_description, transaction_amount
WHERE epk_id = '2099007770421989000001'
ORDER BY event_dt ASC, event_dttm_readable ASC
```

Пример агрегации:

```text
query:
LOAD cards
PERIOD event_dt FROM '20260101' TO '20260131'
SELECT event_description, COUNT(*) AS events_count, sum(transaction_amount_in_rub) AS amount_rub
GROUP BY event_description
ORDER BY events_count DESC
```

Пример вычисляемой колонки:

```text
query:
LOAD cards
PERIOD event_dt FROM '20260101' TO '20260131'
DERIVE event_month = year_month(event_dt)
SELECT event_month, count(event_id) AS events_count
WHERE event_month = '202601'
GROUP BY event_month
```

Поддерживаемые операторы фильтра:

```text
=, !=, <>, >, >=, <, <=, LIKE, CONTAINS, IN (...), BETWEEN, AND, OR
```

Поддерживаемые операции для `DERIVE`:

```text
year, month, year_month, date, lower, upper, length, abs
```

Поддерживаемые агрегаты:

```text
count, count_distinct, min, max, sum, mean. `COUNT(*)` разрешён.
```

## Skills

Skills лежат в:

```text
deep_agent/skills
```

Каждый skill - это папка с коротким файлом `SKILL.md`. Он должен описывать один
понятный участок домена: таблицу, правило поиска или тип аналитического запроса.
`SKILL.md` попадает в preload context, поэтому держите его компактным.

Frontmatter должен содержать только `name` и `description`. Всё, что влияет на выбор
skill, включая trigger-слова и ситуации использования, должно находиться в
`description`.

Подробный контекст выносится в соседние файлы:

- `fields.md` - полный список полей и описания редких колонок;
- `joins.md` - правила связи таблиц и fallback-маршруты;
- другие файлы - только если они читаются по явному триггеру из `SKILL.md`.

Пример структуры:

```text
skills/hit-table/SKILL.md
skills/hit-table/fields.md
skills/hit-table/joins.md
skills/cards-event-table/SKILL.md
skills/cards-event-table/fields.md
skills/uko-event-table/SKILL.md
skills/uko-event-table/fields.md
```

Когда добавлять новый skill:

- появилась новая таблица;
- появились новые поля с важными правилами интерпретации;
- агент часто ошибается в одном и том же типе запроса;
- нужно зафиксировать правила связи между источниками.

Как добавлять:

- в `SKILL.md` добавляйте только назначение источника, alias, зерно, ключи, главные
  поля, критические ограничения и ссылки на дополнительные файлы;
- полный список полей добавляйте в `fields.md`;
- в `SKILL.md` явно пишите, когда читать `fields.md` или `joins.md`, например:
  schema error, редкое поле, вопрос про смысл поля, маршрут связи.

Когда не добавлять новый skill:

- правило нужно только для одного конкретного запуска;
- это временная подсказка;
- это можно выразить в пользовательском запросе.

## Как переиспользовать в другом проекте

1. Подключите пакет `deep_agent` к проекту.
2. Передайте совместимую LangChain chat model.
3. Соберите Spark session или собственный `load_data`.
4. Проверьте, что источник видит таблицы, описанные в skills.
5. Обновите `deep_agent/skills` под свой домен.
6. При необходимости переопределите `deep_agent/config/defaults.json` через
   `DEEP_AGENT_CONFIG_PATH`.

Код агента не должен знать бизнес-смысл таблиц. Этот смысл должен жить в skills:
короткая маршрутизация в `SKILL.md`, подробности в `fields.md` и `joins.md`.
Так пакет проще переносить между проектами: код отвечает за механику, skills отвечают
за домен.
