# Deep Agent

Это аналитический DeepAgent для работы с корпоративными Spark-таблицами, кодом и файлами. Я разделил его на главный `supervisor`, два специализированных подагента, tools, middleware, prompts и skills. Этот README — не только инструкция по запуску, а карта проекта для передачи разработки: где лежит каждая часть, как части связаны и что именно нужно менять для каждого варианта кастомизации.

## Что находится в проекте

Главный сценарий такой:

```text
пользователь
  -> Deep Agents UI
  -> LangGraph Agent Server
  -> user_config/langgraph_agent_server.py:agent
  -> deep_agent.agent.build_agent(...)
  -> supervisor
       -> локальные tools
       -> coding-agent
       -> data-retrieval-agent
            -> load_data
            -> Spark / YARN
```

Роли разделены по ответственности:

| Роль | За что отвечает |
| --- | --- |
| `supervisor` | Понимает запрос, выбирает skills, строит план, делегирует крупные этапы и собирает финальный ответ. |
| `coding-agent` | Пишет и проверяет код, работает с файлами и notebook, считает метрики по уже выгруженным данным. |
| `data-retrieval-agent` | Подтверждает источник, вызывает data-tools, сохраняет полный результат и возвращает компактные evidence. |

Имена, описания и конфигурации подагентов находятся в `deep_agent/subagents.py`. Их prompts лежат отдельно в `deep_agent/prompts/`.

### Что настроить перед первым запуском

В `user_config/langgraph_agent_server.py` нужно заполнить `KITAI_MODEL_CONFIG`:

```python
KITAI_MODEL_CONFIG = {
    "kitai_host_sdk": "https://...",
    "cert_file": "/absolute/path/client.crt",
    "key_file": "/absolute/path/client.key",
    "model": "GigaChat-2-Max",
}
```

Spark настраивается в `create_spark_session()` того же файла.

## Как собирается агент

### Точки входа

1. `run_ui.py` проверяет Python и frontend, запускает Agent Server и UI.
2. `local_ui/langgraph.json` объявляет graph `analytics-agent` и указывает на `user_config/langgraph_agent_server.py:agent`.
3. При импорте выполняется `agent = build_langgraph_agent_server_agent()`.
4. Adapter собирает `AgentSettings`, логгер запросов, KitAI-модель и список Spark data-tools.
5. Adapter вызывает  функцию `deep_agent.agent.build_agent(...)`.
6. `build_agent(...)`  передаёт сборку в `deep_agent.agent_graph_builder`.
7. Builder создаёт backends, tools, middleware, два compiled subagent graph и финальный supervisor graph.

схема внутренних вызовов:

```text
build_agent(...)
  -> _normalize_tools(...)
  -> _register_deepagents_profile(...)
  -> _find_spark_session_factory(...)
  -> _build_agent_context(...)
  -> wrap_data_tools_with_query_code(...)
  -> _build_agent_backends(...)
  -> _build_agent_tools(...)
  -> _build_skills_middleware(...)
  -> _build_subagent_graphs(...)
       -> _build_coding_agent_graph(...)
       -> _build_data_retrieval_agent_graph(...)
  -> _build_supervisor_graph(...)
```


 `deep_agent` экспортирует четыре имени: `build_agent`, `AgentSettings`, `load_agent_settings` и `build_gigachat_kitai_model`.

```python
build_agent(
    *,
    model,
    data_tools,
    settings=None,
    supervisor_tools=None,
    workspace_root=None,
    checkpointer=<internal default>,
    state_artifacts_virtual_dir=None,
    system_prompt_suffix=None,
    request_logger=None,
)
```

- `model` обязателен и используется всеми тремя ролями.
- `data_tools` обязателен: можно передать один `BaseTool` или список.
- `supervisor_tools` —  tools только для supervisor.
- `settings` — готовый `AgentSettings`;
- `workspace_root` переопределяет путь из settings.
- если `checkpointer` не передан, создаётся `InMemorySaver`;
- `state_artifacts_virtual_dir` задаёт виртуальный путь для файлов UI;
- `system_prompt_suffix` дописывается только к prompt supervisor;
- `request_logger` включает middleware логирования пользовательских запросов.

Перед регистрацией graph функция через `HarnessProfile` отключает стандартный base prompt и автоматический `general-purpose` subagent DeepAgents. Поэтому в runtime остаются только явно собранные роли проекта.

### Ключевые классы

| Класс/контейнер | Создаётся в | Кому передаётся и зачем |
| --- | --- | --- |
| `AgentSettings` | `agent_settings.py` | В `build_agent`, затем во все builders, backends и middleware с лимитами. |
| `DeepAgentsKitaiChatModel` | `gigachat_kitai_model.py` | Одна model для supervisor, подагентов, skills selector и review-agent. |
| `_AgentBuildContext` | `agent_graph_builder.py` | Собирает вычисленные пути, model, settings, checkpointer, logger и Spark factory одного graph. |
| `_AgentBackends` | `agent_graph_builder.py` | Хранит три backend: supervisor, coding и data. |
| `_AgentTools` | `agent_graph_builder.py` | Хранит готовые экземпляры project tools и role-specific входные списки. |
| `_SkillsMiddlewareBundle` | `agent_graph_builder.py` | Связывает selector supervisor и consumer data-agent общим `shared_selection`. |
| `AnalyticsAgentState` | `agent_state.py` | Базовая state schema для private skills fields; её расширяют state-схемы отдельных middleware. |
| `DeepAgentPythonSandbox` | `execution/python_sandbox.py` | Передаётся в один `PythonTool`; globals живут между вызовами этого graph. |
| `PythonTool` | `tools/python_execution_tool.py` | Один экземпляр передаётся всем трём ролям. |
| `WorkspaceFilesystemMixin` -> `WorkspaceReadMixin` | `execution/filesystem_backend.py` | Общие workspace paths, запись, notebook и pagination для двух backend. |
| `Utf8LocalShellBackend` | `build_shell_workspace_backend()` | Backend supervisor/coding с filesystem и shell. |
| `Utf8FilesystemBackend` | `build_filesystem_workspace_backend()` | Backend data-agent и read-only review-agent без shell. |
| `ReadTableInput` -> `ParsedDataQuery` | `data_processing/load_data_query_models.py` | Первая схема валидирует tool call, вторая принимает structured output parser и идёт в Spark pipeline. |
| `UserProfileMemory` | `memory/user_profile_memory.py` | Ссылка на profile file передаётся в `UserProfileMemoryMiddleware`, затем путь читает `MemoryMiddleware`. |
| `AgentRequestLogger` | `middleware/request_logging_middleware.py` | Adapter создаёт/инициализирует logger и передаёт его в `AgentRequestLoggingMiddleware`. |

## Workspace, backends и пути

Примеры:

```text
/skills/hit-table/SKILL.md
/artifacts/load_data_hits_where_event_dt_between_20260701_20260713_main_rule_contains_deny_20260713_154230_128441.jsonl
/deepagent/AGENTS.md
```

Имя Spark artifact строится без hash: в него последовательно входят источник,
читаемые фрагменты фильтров и время создания. Поля результата, grouping,
aggregations, derived columns, sorting и limit в имя не добавляются. Поэтому модель
и человек могут понять назначение файла по короткому пути, а повторная выгрузка не
перезаписывает предыдущий результат.


`FilesystemPathContractMiddleware` нормализует пути tool calls и добавляет preview файловых операций. Это удобный контракт путей, но не отдельная песочница безопасности. Аналогично `python` называется sandbox, но выполняет Python в процессе и должен считаться доверенным инструментом внутри разрешённого workspace.

Shell backend создаётся с `env={}` и `inherit_env=False`: переменные окружения процесса в shell tool автоматически не наследуются. Если новой команде нужны PATH, credentials или другие env, это надо настраивать явно и отдельно оценивать с точки зрения секретов.

`/artifacts/` — зарезервированный реальный каталог workspace. Для него не создаётся отдельный `StateBackend`, чтобы все роли читали один и тот же файл с диска. Для другого `state_artifacts_virtual_dir` builder может создать route в `StateBackend`.

## Как передаётся SparkSession

Это место важно понимать точно: по graph не передаётся готовая `SparkSession`. Передаётся фабрика `Callable[[], SparkSession]`.

### Основной путь `load_data`

```text
create_spark_session
  -> build_spark_data_tools(spark_session_factory=...)
  -> closure read_table(query)
  -> tool.metadata["spark_session_factory"]
  -> build_agent(data_tools=[load_data])
  -> data-retrieval-agent
  -> вызов load_data
  -> _managed_spark_session(factory)
  -> _read_table(spark=session, ...)
  -> cancel jobs + spark.stop()
```

`build_spark_data_tools(...)` делает две вещи с фабрикой:

1. замыкает её внутри функции `read_table(query)`;
2. сохраняет её в `tool.metadata["spark_session_factory"]`.

`build_agent(...)` ищет первый callable с таким metadata среди исходных `data_tools`. Имя tool при поиске не проверяется. Найденная фабрика используется для профиля пользователя, а сам `load_data` после обёртки попадает только в `data-retrieval-agent`.

На каждом вызове `load_data`:

1. LLM parser преобразует SQL-похожий `query` в `ParsedDataQuery`.
2. `_managed_spark_session` вызывает фабрику.
3. Сессия регистрируется в списке активных сессий.
4. `spark.table(...)` строит DataFrame transformations.
5. Выполняются две Spark actions: `count()` и запись результата.
6. Spark writer пишет part-файлы во временную папку Hadoop home.
7. Part-файлы копируются на локальную файловую систему и объединяются в один JSONL в `artifacts/`.
8. В контекст возвращаются metadata, путь и preview; полный набор остаётся в JSONL.
9. В `finally` отменяются активные jobs, вызывается best-effort `spark.stop()`, сессия удаляется из реестра.

Модуль также регистрирует `atexit` и обработчики `SIGINT`, `SIGTERM`, а на Windows ещё `SIGBREAK`, чтобы аварийно остановить зарегистрированные сессии.

Внутри процесса весь блок `load_data`, включая Spark actions, защищён общим lock. Поэтому два `load_data` в одном Python-процессе выполняются последовательно.

### Важная оговорка про `getOrCreate()`

Текущая `create_spark_session()` заканчивается на `SparkSession.builder.getOrCreate()`. Фабрика вызывается для каждого tool call, но `getOrCreate()` может вернуть уже существующую session/SparkContext. При этом `load_data` считает полученный объект принадлежащим текущему вызову и останавливает его после завершения.

Поэтому нельзя без дополнительной проверки передавать сюда shared session, которую использует другой код. Если нужна безопасная параллельность или переиспользование контекста, lifecycle фабрики и политика `stop()` должны быть переработаны вместе.

### Второй потребитель Spark: профиль пользователя

Если среди data-tools найдена фабрика, `build_agent(...)` автоматически создаёт ссылку на `/.deep_agent/memory/user_profile.md` и добавляет `UserProfileMemoryMiddleware` supervisor-у.

При первом запросе middleware:

1. пытается извлечь числовой login из пути workspace;
2. если актуального profile-файла нет, отдельно вызывает ту же Spark factory;
3. читает `csp_addressbook_inc.base` по `domainloginsigma`;
4. сохраняет login и ФИО в profile-файл;
5. вызывает `spark.stop()` в `finally`;
6. затем обычный `MemoryMiddleware` добавляет профиль в memory supervisor.

Этот lifecycle не использует lock и реестр активных сессий `load_data`. При `getOrCreate()` параллельный profile query и `load_data` теоретически могут получить общий объект и остановить его друг у друга. Это текущий технический риск.

Профиль создаётся только если metadata `spark_session_factory` найден. Если новый data-tool должен участвовать в этом механизме, положи callable в metadata. Если фабрик несколько, сейчас будет выбрана первая — явного выбора по имени нет.

### HITL отсутствует

Spark-запрос выполняется без остановки graph и пользовательского подтверждения. В tool нет `interrupt`, `require_approval` и вспомогательных функций approval.

## Как работает `load_data`

Внешняя схема tool очень маленькая: `ReadTableInput` содержит один SQL-похожий `query`. Внутри запрос разбирается моделью в:

- `table_name`;
- `select_columns`;
- `filters`;
- `derived_columns`;
- `group_by`;
- `aggregations`;
- `order_by`;
- `max_rows`.

Период обязателен, кроме точного фильтра `event_id = ...`. `SELECT *` не является штатным контрактом. `LIMIT` должен появляться только по явному запросу пользователя.

Основная цепочка файлов:

```text
tools/load_data_spark_tool.py
  -> data_processing/load_data_query_parser.py
  -> data_processing/load_data_query_models.py
  -> data_processing/load_data_query_values.py
  -> data_processing/load_data_spark_query.py
  -> data_processing/load_data_spark_execution.py
  -> data_processing/load_data_result.py
```

`wrap_data_tools_with_query_code(...)` сохраняет имя, описание и args schema исходного tool, переводит ответ в `content_and_artifact` и добавляет информацию о фактическом запросе. Для файлового Spark-результата полный набор остаётся в JSONL и повторно в pickle не копируется.

Отдельного middleware для повторного сохранения табличных результатов нет: текущий `load_data` сам сохраняет полный результат в JSONL и возвращает preview с путём к файлу.

## Tools

### Проектные tools

| Tool | Где создаётся | Схема | Кто получает явно |
| --- | --- | --- | --- |
| `load_data` | `tools/load_data_spark_tool.py` | `ReadTableInput` | Только `data-retrieval-agent`. |
| `python` | `tools/python_execution_tool.py` | `PythonInput` | Все три роли. |
| `load_skills` | `tools/skill_loader_tool.py` | Аргументы factory-функции | Все три роли. |
| `get_project_structure` | `tools/project_structure_tool.py` | `GetProjectStructureInput` | Supervisor и coding-agent. |
| `convert_jupyter_notebook` | `tools/jupyter_notebook_tool.py` | `ConvertJupyterNotebookInput` | Только coding-agent. |
| `review_refactor` | `tools/refactor_review_tool.py` | `ReviewRefactorInput` | Только coding-agent. |

`python` использует один persistent `DeepAgentPythonSandbox`, созданный на graph. Его globals сохраняются между вызовами. В него заранее добавляются `PROJECT_ROOT`, `WORKSPACE_ROOT`, `ARTIFACTS_DIR`, `resolve_workspace_path`, helpers для pickle и, если установлены, `pd`/`np`.

Кроме проектных tools, `create_deep_agent(...)` добавляет нативные tools DeepAgents: todo, task/subagents, filesystem и shell в зависимости от backend. Точный итоговый набор зависит от установленной версии `deepagents`; его можно увидеть в `debug_prompts/*.json`, потому что `PromptLoggingMiddleware` сохраняет фактический `ModelRequest.tools`.

### Что видит каждая роль сейчас

| Роль | Явно переданные tools | Backend/native возможности | Скрыто от модели |
| --- | --- | --- | --- |
| `supervisor` | `load_skills`, `python`, `get_project_structure`, все `supervisor_tools` | filesystem, shell/`execute`, todo, `task` | `edit_file` |
| `coding-agent` | `load_skills`, `python`, `get_project_structure`, `convert_jupyter_notebook`, `review_refactor` | filesystem, shell/`execute`, todo | `edit_file` |
| `data-retrieval-agent` | все `data_tools`, `load_skills`, `python` | filesystem без shell, todo | `edit_file` |

Важно: скрытие через `PromptToolFilterMiddleware` убирает metadata tool только из запроса к модели. Оно не удаляет реализацию из backend и не является security boundary. Например, `write_file` остаётся видимым, а supervisor/coding-agent имеют shell. Для настоящего запрета tool надо не регистрировать, выбрать backend без этой возможности или добавить проверяющий middleware.

### Как добавить новый tool через `StructuredTool`

Для обычной функции я использую `StructuredTool.from_function`. По правилам проекта файл, функция и Pydantic-схема должны иметь русские docstrings.

```python
"""Инструмент поиска записей.

Содержит:
- SearchRecordsInput: входная схема поиска;
- search_records: выполнение поиска;
- build_search_records_tool: сборка LangChain tool.
"""

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field


class SearchRecordsInput(BaseModel):
    """Аргументы поиска записей.

    Args:
        query: Текст поискового запроса.
    """

    query: str = Field(description="Что нужно найти.")


def search_records(query: str) -> str:
    """Ищет записи по тексту.

    Args:
        query: Текст поискового запроса.

    Returns:
        JSON-строку с найденными записями.
    """

    return "..."


def build_search_records_tool() -> BaseTool:
    """Собирает инструмент поиска.

    Returns:
        Готовый LangChain tool `search_records`.
    """

    return StructuredTool.from_function(
        func=search_records,
        name="search_records",
        description="Ищет записи по текстовому описанию.",
        args_schema=SearchRecordsInput,
    )
```

Дальше выбираю область видимости:

- только supervisor — создать tool в adapter и передать `supervisor_tools=[tool]` в `build_agent(...)`;
- только data-agent — передать его в `data_tools=[...]`; учесть, что все data-tools проходят через `wrap_data_tools_with_query_code(...)`;
- только coding-agent — добавить поле в `_AgentTools`, собрать tool в `_build_agent_tools(...)` и включить его в список `_build_coding_agent_graph(...)`;
- несколько внутренних ролей — собрать один экземпляр в `_build_agent_tools(...)` и добавить в нужные role-specific списки.

Для сложного stateful tool можно наследоваться от `BaseTool`, как сделано в `PythonTool`, `GetProjectStructureTool` или `ConvertJupyterNotebookTool`.

Внутри `review_refactor` создаётся ещё один служебный `review-refactor-agent`. Он работает на `Utf8FilesystemBackend` с read-only permission, prompt filter и prompt logging. Для него скрыты write/shell/todo/task tools. Это отдельный graph внутри tool, а не третий подагент supervisor.

### Как добавить Spark/data tool

Если tool самостоятельно управляет SparkSession, передавать сам объект через graph не надо. Передавай factory в closure. Если этот tool должен также включить user-profile memory, добавь:

```python
tool.metadata = {
    **(tool.metadata or {}),
    "spark_session_factory": spark_session_factory,
}
```

Учитывай текущий контракт ownership: код профиля и `load_data` вызывают `stop()` на полученной session. Нельзя класть в metadata factory, которая возвращает чужую shared session, пока lifecycle не изменён.

### Как изменить имя и описание tool

- у `BaseTool` имя задаётся полем `name`, описание — полем `description`;
- у `StructuredTool` — аргументами `name=` и `description=`;
- описания наших tools хранятся рядом с реализацией в константах вроде `PYTHON_TOOL_DESCRIPTION`;
- prompt-visible описания нативных tools DeepAgents переопределяются в `deep_agent/prompts/tool_description_prompt.py`, словарь `TOOL_DESCRIPTION_OVERRIDES`;
- `PromptToolDescriptionsMiddleware` меняет только описание в запросе к модели, не реализацию.

При переименовании обязательно обновить:

- константу/factory tool;
- role-specific список и `hidden_tool_names`, если имя там используется;
- `TOOL_DESCRIPTION_OVERRIDES`;
- prompts и skills, где имя упоминается;
- middleware, которые проверяют имя tool;
- README и проверки.

### Как скрыть или раскрыть tool

Role-specific `hidden_tool_names` задаются в `deep_agent/agent_graph_builder.py`:

```python
runtime_middleware = _build_native_runtime_middleware(
    ...,
    hidden_tool_names=("edit_file",),
)
```

- чтобы раскрыть tool, убери имя из tuple;
- чтобы скрыть ещё один, добавь его имя;
- чтобы tool вообще не существовал для роли, убери его из `tools=[...]` или смени backend;
- если нужен runtime-запрет с понятной ошибкой, добавь middleware с `wrap_tool_call`/`awrap_tool_call`.

## Middleware

Middleware подключаются списком в `create_deep_agent(...)`. Порядок важен: каждый слой может изменить state, `ModelRequest`, tool call или результат следующего handler.

### Текущий project stack

Общий runtime stack собирает `_build_native_runtime_middleware(...)`:

1. `DiagnosticLoggingMiddleware`;
2. `PromptToolFilterMiddleware`, если есть скрытые имена;
3. `PromptToolDescriptionsMiddleware`;
4. `FilesystemPathContractMiddleware`, если передан workspace root;
5. `ShellSafetyMiddleware`;
6. `LoopBreakerMiddleware`;
7. штатный `ModelRetryMiddleware`;
8. штатный `ContextEditingMiddleware`;
9. штатный `ToolCallLimitMiddleware`;
10. `ToolContextNoticeMiddleware`;
11. штатный `ModelCallLimitMiddleware` для подагентов;
12. `MemoryMiddleware` вставляется role builder перед prompt logger;
13. `PromptLoggingMiddleware`.

Перед этим у supervisor дополнительно стоят:

1. `TodoResetMiddleware`;
2. `AgentRequestLoggingMiddleware`, если передан logger;
3. `UserProfileMemoryMiddleware`, если найдена Spark factory;
4. `PreloadedSkillsContextMiddleware` в режиме выбора.

У data-agent перед runtime stack стоит `PreloadedSkillsContextMiddleware` в режиме чтения общего выбора. У coding-agent этого middleware нет; при необходимости он вызывает `load_skills` явно.

DeepAgents добавляет собственные штатные middleware вокруг переданного списка: todo, filesystem, subagents, summarization, совместимость tool calls и нативный skills catalog. Во все три `create_deep_agent(...)` передаётся `skills=[context.skills_workspace_dir]`, поэтому supervisor и оба подагента видят в prompt индекс доступных skills с их `name` и `description`. Собственный selector и `load_skills` остаются: selector заранее подставляет полный текст релевантных skills, а tool позволяет модели явно дозагрузить нужный skill и связанные файлы.

### Назначение middleware

| Middleware | Фаза | Что делает |
| --- | --- | --- |
| `TodoResetMiddleware` | before/after agent | Сбрасывает старый todo state между пользовательскими turn и после финального ответа. |
| `AgentRequestLoggingMiddleware` | before agent | Один раз пишет новый human request в PostgreSQL. Ошибка логирования не останавливает агента. |
| `UserProfileMemoryMiddleware` | before agent | Один раз пытается создать Spark-профиль пользователя. |
| `PreloadedSkillsContextMiddleware` | before agent/model | Выбирает `SKILL.md`, сохраняет результат в private state и добавляет полный текст в system prompt. |
| `DiagnosticLoggingMiddleware` | model | Печатает начало, успех и ошибку model call. |
| `PromptToolFilterMiddleware` | model | Убирает выбранные tools из metadata, видимых модели. |
| `PromptToolDescriptionsMiddleware` | model | Подменяет descriptions без изменения реализации. |
| `FilesystemPathContractMiddleware` | tool | Нормализует workspace paths и дополняет результат preview. |
| `ShellSafetyMiddleware` | tool | Блокирует известные небезопасные формы shell-команд. |
| `LoopBreakerMiddleware` | before model | Добавляет корректирующее сообщение при повторяющихся ошибках/цикле. |
| `ModelRetryMiddleware` | model | Повторяет только временные/provider errors и форматирует финальную ошибку. |
| `ContextEditingMiddleware` | context | Удаляет старые tool results после token threshold. |
| `ToolCallLimitMiddleware` | tool | Ограничивает общее число tool calls за run. |
| `ToolContextNoticeMiddleware` | tool | Добавляет пояснение о переданном контексте и recovery hint к ошибкам. |
| `ModelCallLimitMiddleware` | model | Ограничивает model calls одного запуска подагента. |
| `MemoryMiddleware` | before agent/model | Читает `AGENTS.md`, а у supervisor ещё user profile. |
| `PromptLoggingMiddleware` | model | Сохраняет фактический prompt, messages и tools в `debug_prompts/*.json`. |

### Как создать middleware

Минимальный шаблон:

```python
"""Middleware проверки вызовов инструментов.

Содержит:
- AllowedToolsMiddleware: проверка разрешённых имён tools.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware


@dataclass(frozen=True)
class AllowedToolsMiddleware(AgentMiddleware):
    """Пропускает только разрешённые инструменты.

    Args:
        allowed_names: Имена tools, которые можно выполнять.
    """

    allowed_names: frozenset[str]

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Проверяет синхронный tool call и возвращает его результат.

        Args:
            request: Запрос на выполнение tool.
            handler: Следующий обработчик middleware chain.

        Returns:
            Результат следующего обработчика.
        """

        name = str(request.tool_call.get("name") or "")
        if name not in self.allowed_names:
            raise PermissionError(f"Tool запрещён: {name}")
        return handler(request)

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Проверяет асинхронный tool call и возвращает его результат.

        Args:
            request: Запрос на выполнение tool.
            handler: Следующий асинхронный обработчик chain.

        Returns:
            Результат следующего обработчика.
        """

        name = str(request.tool_call.get("name") or "")
        if name not in self.allowed_names:
            raise PermissionError(f"Tool запрещён: {name}")
        return await handler(request)
```

Куда подключать:

- всем ролям — `_build_native_runtime_middleware(...)`;
- только supervisor — список `middleware=[...]` в `_build_supervisor_graph(...)`;
- только data-agent — список в `_build_data_retrieval_agent_graph(...)`;
- только coding-agent — список в `_build_coding_agent_graph(...)`;
- внутреннему review-agent — его отдельная сборка в `tools/refactor_review_tool.py`.

Если middleware добавляет private state, расширяй `AnalyticsAgentState` или создай отдельную TypedDict-схему по примеру `RequestLoggingState`/`TodoResetState` и укажи `state_schema`.

## Skills

`skills/` содержит доменные знания и рабочие сценарии. Код менять не нужно, если задача решается добавлением знаний.

Обычная структура:

```text
skills/<skill-name>/
  SKILL.md     # короткая карточка для выбора
  README.md    # подробное объяснение для человека
  fields.md    # полный список полей, если нужен
  joins.md     # правила связей, если нужны
```

В `SKILL.md` держу только то, что нужно модели для маршрутизации: когда использовать skill, источник, ключевые поля, обязательные фильтры и ограничения. Большие справочники выношу в соседние файлы.

### Как skills попадают в контекст

1. Нативный `SkillsMiddleware` DeepAgents добавляет в prompt каждой роли индекс доступных skills с `name` и `description`.
2. Поэтому supervisor, coding-agent и data-agent знают, какие skills существуют, и могут осознанно вызвать `load_skills`.
3. Дополнительно supervisor middleware рекурсивно находит `SKILL.md` и строит свой компактный index для автоматического выбора.
4. Та же chat model делает structured selection по последнему user query.
5. Пути валидируются; при ошибке предусмотрена одна исправляющая попытка.
6. Полный текст выбранных `SKILL.md` читается с лимитом и сохраняется в private state.
7. Supervisor получает этот текст в system message.
8. Data-agent использует общий in-memory selection cache и получает тот же контекст без второго selector call.
9. Любая роль при необходимости явно загружает полный skill или связанные файлы через `load_skills`.

`load_skills` умеет искать skill по имени/path и дозагружать связанные markdown-файлы. Ограничения и правила устройства каталога описаны в `skills/README.md`.

Нативный index, автоматический selector и `load_skills` намеренно работают вместе: index сообщает основной модели о доступных skills, selector заранее добавляет наиболее релевантные инструкции, а tool оставляет модели возможность самостоятельно загрузить дополнительные материалы.

### Как добавить skill

1. Создать `skills/<name>/SKILL.md`.
2. В первых 20 строках добавить однострочные `name:` и `description:` без отступа. Текущий parser не понимает многострочный YAML description.
3. Сослаться на точные table names, поля и ограничения — не придумывать их в prompt.
4. Большие списки вынести в `fields.md`, связи — в `joins.md`, человеческое объяснение — в `README.md`.
5. Проверить вопросом, что selector выбрал skill; результат виден в state/debug prompt.

Index ручного `load_skills` строится при создании tool. Если добавить новый skill в уже работающий процесс, для появления в lookup надо пересобрать graph/перезапустить Agent Server. Автоматический selector supervisor сканирует `SKILL.md` при выборе, но рассчитывать на частично обновлённый graph не стоит.

## Prompts и модель

| Что меняю | Файл |
| --- | --- |
| Поведение supervisor | `deep_agent/prompts/supervisor_prompt.py` |
| Поведение coding-agent | `deep_agent/prompts/coding_agent_prompt.py` |
| Поведение data-retrieval-agent | `deep_agent/prompts/data_retrieval_agent_prompt.py` |
| Выбор/вставку skills | `deep_agent/prompts/skills_context_prompt.py` и selector prompt внутри middleware |
| Разбор SQL-похожего query | `deep_agent/prompts/load_data_query_parser_prompt.py` |
| Review refactor | `deep_agent/prompts/refactor_review_prompt.py` |
| Описания нативных tools | `deep_agent/prompts/tool_description_prompt.py` |

`system_prompt_suffix` дописывает инструкции только supervisor. Для подагентов нужно менять их prompt constants или расширять builder.

`DeepAgentsKitaiChatModel` адаптирует content blocks LangChain к строкам KitAI, сохраняет служебный `functions_state_id` и сообщает DeepAgents provider/model через `_get_ls_params`. Смена провайдера возможна: передай другой `BaseChatModel` в `build_agent(...)`, но проверь совместимость tool calls, structured output selector и зарегистрированный harness profile.

Сейчас одна и та же model используется supervisor, обоими подагентами, selector skills и внутренним refactor reviewer. Публичного аргумента для разных моделей по ролям нет; для этого надо расширять `_AgentBuildContext` и role builders.

## Как добавить нового подагента

Текущая сборка жёстко знает два подагента. Для третьего нужно изменить несколько связанных мест:

1. Создать отдельный prompt в `deep_agent/prompts/`.
2. В `deep_agent/subagents.py` добавить имя и routing description для supervisor.
3. В `_AgentTools`/`_AgentBackends` добавить нужные зависимости, если существующих недостаточно.
4. В `deep_agent/agent_graph_builder.py` создать `_build_<name>_agent_graph(...)`.
5. Выбрать backend: shell или filesystem-only.
6. Собрать его role-specific tools и middleware.
7. В `_build_subagent_graphs(...)` скомпилировать graph.
8. Добавить compiled runnable в список, который возвращает `_build_subagent_graphs(...)`.
9. Обновить supervisor prompt, tool visibility table и проверки.

Описание подагента должно объяснять supervisor, когда делегировать задачу и какой evidence вернуть. Prompt подагента отвечает уже за выполнение внутри роли.

## State, memory, persistence и логи

### State

`AnalyticsAgentState` расширяет стандартный `AgentState` private-полями выбора skills:

- загружен ли контекст;
- ключ user query;
- выбранные пути;
- полный текст;
- status/reason/error selector;
- факт retry и validation errors;
- materialized paths.

Отдельные middleware добавляют свои private state fields для deduplication request logging и todo reset.

### Memory

- `AGENTS.md` читается `MemoryMiddleware` всеми ролями.
- user profile читается только supervisor.
- `build_agent()` без явного checkpointer создаёт process-local `InMemorySaver`.
- UI adapter передаёт `checkpointer=None`, потому что threads/persistence обеспечивает Agent Server.
- Локальный `langgraph dev` держит рабочие структуры в памяти, но примерно раз в 10 секунд
  сохраняет их в `<cwd>/.langgraph_api/*.pckl`. `run_ui.py` запускает backend с `cwd` в корне
  проекта, поэтому после перезапуска threads и checkpoints восстанавливаются из
  `<project>/.langgraph_api`. Каталог создаётся только после фактического запуска Agent Server.
- UI передаёт при новом ходе только новое сообщение и `threadId`: накопленный `state.messages`
  Agent Server восстанавливает из checkpoint соответствующего thread.
- `.deep_agent/memory/user_profile.md` — runtime-файл и не коммитится.

### Логирование запросов

Управляется env:

```text
DEEP_AGENT_REQUEST_LOGGING_ENABLED=true
DEEP_AGENT_REQUEST_LOG_DSN=postgresql+driver://...
DEEP_AGENT_REQUEST_LOG_SCHEMA=user
DEEP_AGENT_REQUEST_LOG_TABLE=agent_request_logs
```

Если флаг выключен или DSN пустой, logger не создаётся. При включении adapter заранее создаёт schema/table, а middleware пишет `request_text`, `user_login`, `requested_at` один раз на human turn.

### Диагностика

- `local_ui/.runtime/logs/` — stdout/stderr Agent Server;
- `debug_prompts/*.json` — итоговый `ModelRequest` каждой роли;
- `artifacts/*.jsonl` — полные Spark-выгрузки;
- `.deep_agent/review_snapshots/` — snapshots для refactor review;
- `.deep_agent/notebook_scripts/` — cache конвертации notebook;

## Настройки `AgentSettings`

Defaults находятся в `deep_agent/agent_settings.py`. Для runtime-изменений лучше собрать объект и применить `dataclasses.replace`, как делает UI adapter:

```python
from dataclasses import replace

from deep_agent.agent_settings import load_agent_settings

settings = replace(
    load_agent_settings(WORKSPACE_ROOT),
    max_tool_calls_per_run=60,
    max_subagent_model_calls=25,
)
```

| Поле | Default | Что контролирует |
| --- | ---: | --- |
| `workspace_root` | корень проекта | Реальный корень файлового пространства. |
| `agents_file_name` | `AGENTS.md` | Project memory path внутри workspace. |
| `terminal_timeout` | `120` | Timeout shell-команды, секунд. |
| `terminal_max_output_bytes` | `100000` | Максимальный stdout/stderr shell tool. |
| `skills_root` | `<workspace>/skills` | Каталог skills. |
| `tool_outputs_dir` | `<workspace>/artifacts` | JSONL и пользовательские artifacts. |
| `context_edit_trigger_tokens` | `100000` | Порог очистки старых tool results. |
| `context_edit_keep_tool_results` | `3` | Сколько последних tool results сохранить. |
| `read_file_default_limit` | `500` | Default line limit чтения файлов. |
| `max_model_retries` | `5` | Повторы временной ошибки модели. |
| `max_tool_calls_per_run` | `40` | Общий бюджет tool calls. |
| `max_subagent_model_calls` | `19` | Бюджет model calls подагента. |

Пути `skills_root` и `AGENTS.md` обязаны разрешаться внутри workspace. `tool_outputs_dir` может остаться внешним абсолютным путём. Виртуальные tool paths всегда нормализуются к `/...`.

## Карта кастомизации

| Задача | Что менять |
| --- | --- |
| Новый доменный источник/правило | `skills/<name>/` без изменения Python-кода. |
| Новый prompt роли | Соответствующий файл `deep_agent/prompts/`. |
| Дополнительная инструкция только supervisor | `system_prompt_suffix` в `build_agent(...)`. |
| Новая модель | Создать `BaseChatModel` и передать `model=`. |
| Настройки KitAI | `KITAI_MODEL_CONFIG` в adapter. |
| Spark resources/HDFS/client paths | `create_spark_session()` в adapter. |
| Новый tool supervisor | `supervisor_tools=`. |
| Новый data tool | `data_tools=`; при необходимости metadata Spark factory. |
| Новый internal tool coding-agent | `_AgentTools`, `_build_agent_tools`, `_build_coding_agent_graph`. |
| Скрыть tool от prompt | `hidden_tool_names`. |
| Реально удалить возможность | Убрать регистрацию, сменить backend или поставить blocking middleware. |
| Изменить native tool description | `TOOL_DESCRIPTION_OVERRIDES`. |
| Новый middleware всех ролей | `_build_native_runtime_middleware`. |
| Middleware одной роли | Соответствующий `_build_*_graph`. |
| Новый подагент | prompt + `subagents.py` + graph builder + supervisor configs. |
| Другой workspace/artifacts | `AgentSettings` или аргументы `build_agent`. |
| Другой persistence | `checkpointer=`. |
| Включить request log | env-переменные `DEEP_AGENT_REQUEST_LOG_*`. |
| Изменить UI/порты | параметры `run_ui.py`. |

Публичного `middleware=` аргумента и публичного `coding_tools=` аргумента сейчас нет. Наличие `langchain-mcp-adapters` в dependencies тоже не означает готовую MCP-интеграцию: MCP servers/tools в коде не подключены.

## Полная карта файлов

Ниже перечислены проектные файлы. Runtime/generated каталоги перечислены отдельно и в Git не входят.

### Корень

- `README.md` — этот документ.
- `AGENTS.md` — правила разработки и project memory для агентов.
- `pyproject.toml` — пакет, Python-зависимости, extras, setuptools и Ruff.
- `run_ui.py` — offline launcher backend + frontend.
- `.gitignore` — runtime, artifacts, окружения и локальные секреты.
- `SHA256SUMS` — checksum полного offline UI archive.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part001` — часть 1 offline archive.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part002` — часть 2.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part003` — часть 3.
- `deep-agents-ui-node20-linux-x86_64.tar.gz` — локально собранный полный archive; игнорируется Git.

### `user_config/`

- `user_config/langgraph_agent_server.py` — production/local adapter: workspace, KitAI, Spark factory, request logger, data-tools и экспорт `agent`.

### `deep_agent/`

- `deep_agent/__init__.py` — пакет.
- `deep_agent/README.md` — короткая карта core.
- `deep_agent/_request_log_config.py` — env-конфигурация PostgreSQL request logger.
- `deep_agent/agent.py` — публичный `build_agent`, backend builders, path helpers и поиск Spark factory.
- `deep_agent/agent_graph_builder.py` — пошаговая сборка context/backends/tools/middleware/subagents/supervisor.
- `deep_agent/agent_settings.py` — `AgentSettings`, defaults и преобразование workspace paths.
- `deep_agent/agent_state.py` — `AnalyticsAgentState` и чтение messages.
- `deep_agent/gigachat_kitai_model.py` — адаптер KitAI/GigaChat к LangChain/DeepAgents.
- `deep_agent/subagents.py` — имена и routing descriptions подагентов.

### `deep_agent/data_processing/`

- `deep_agent/data_processing/__init__.py` — пакет.
- `deep_agent/data_processing/load_data_query_models.py` — Pydantic-модели filters/derived/aggregations/order/parser result/tool input.
- `deep_agent/data_processing/load_data_query_parser.py` — LLM structured parser, fallback/repair и валидация периода.
- `deep_agent/data_processing/load_data_query_values.py` — разбор строковых значений query structures.
- `deep_agent/data_processing/load_data_spark_query.py` — построение transformations и реального PySpark-кода.
- `deep_agent/data_processing/load_data_spark_execution.py` — Spark actions, progress, cancel, Hadoop temp, copy/merge JSONL.
- `deep_agent/data_processing/load_data_result.py` — transparency wrapper `content_and_artifact` и формат результата.

### `deep_agent/execution/`

- `deep_agent/execution/__init__.py` — пакет.
- `deep_agent/execution/filesystem_backend.py` — UTF-8 filesystem/shell backend, virtual paths, notebook cache и review snapshots.
- `deep_agent/execution/python_sandbox.py` — persistent Python globals и helpers для workspace/artifacts.

### `deep_agent/memory/`

- `deep_agent/memory/__init__.py` — пакет.
- `deep_agent/memory/user_profile_memory.py` — profile path, login extraction, Spark addressbook query и markdown profile.

### `deep_agent/middleware/`

- `deep_agent/middleware/__init__.py` — пакет.
- `deep_agent/middleware/README.md` — короткая карта middleware.
- `deep_agent/middleware/filesystem_path_middleware.py` — path normalization и file operation preview.
- `deep_agent/middleware/gigachat_runtime_middleware.py` — shell safety и loop breaker.
- `deep_agent/middleware/model_error_middleware.py` — retry predicate, status extraction и redaction ошибки.
- `deep_agent/middleware/prompt_logging_middleware.py` — JSON-лог фактического model request.
- `deep_agent/middleware/request_logging_middleware.py` — PostgreSQL logger и deduplication human turns.
- `deep_agent/middleware/skills_context_middleware.py` — discovery, selector, validation, shared selection и prompt injection skills.
- `deep_agent/middleware/todo_reset_middleware.py` — очистка todo state.
- `deep_agent/middleware/tool_context_middleware.py` — context notice и recovery hint.
- `deep_agent/middleware/tool_description_middleware.py` — diagnostic, description override и prompt-only filter.
- `deep_agent/middleware/user_profile_memory_middleware.py` — отложенное создание user profile до чтения memory.

### `deep_agent/prompts/`

- `deep_agent/prompts/__init__.py` — пакет.
- `deep_agent/prompts/README.md` — карта prompts.
- `deep_agent/prompts/supervisor_prompt.py` — system prompt supervisor.
- `deep_agent/prompts/coding_agent_prompt.py` — system prompt coding-agent.
- `deep_agent/prompts/data_retrieval_agent_prompt.py` — system prompt data-agent.
- `deep_agent/prompts/load_data_query_parser_prompt.py` — parser prompt SQL-like -> Pydantic.
- `deep_agent/prompts/refactor_review_prompt.py` — prompt read-only review-agent.
- `deep_agent/prompts/skills_context_prompt.py` — шаблоны preloaded skills для ролей.
- `deep_agent/prompts/tool_description_prompt.py` — descriptions нативных DeepAgents tools.

### `deep_agent/tools/`

- `deep_agent/tools/__init__.py` — пакет.
- `deep_agent/tools/README.md` — короткая карта tools.
- `deep_agent/tools/load_data_spark_tool.py` — Spark `load_data`, lifecycle session и cleanup.
- `deep_agent/tools/python_execution_tool.py` — LangChain `PythonTool`, policy checks и JSON-result.
- `deep_agent/tools/python_execution_helpers.py` — форматирование workspace paths/artifacts для Python tool.
- `deep_agent/tools/skill_loader_tool.py` — поиск и чтение skill context files.
- `deep_agent/tools/project_structure_tool.py` — компактное дерево проекта.
- `deep_agent/tools/jupyter_notebook_tool.py` — `.py` <-> `.ipynb`.
- `deep_agent/tools/jupyter_notebook_formatting.py` — разметка/форматирование notebook cells.
- `deep_agent/tools/refactor_review_tool.py` — read-only review-agent для результата рефакторинга.

### `docs/`

- `docs/agent_architecture.md` — расширенная архитектурная схема.
- `docs/agent_data_structure.md` — единая схема graph/state/data/artifacts.
- `docs/middleware_map.md` — карта middleware по ролям и фазам.
- `docs/request_lifecycle.md` — последовательность одного пользовательского запроса.

Эти документы полезны как схемы, но при расхождении источником истины остаётся код и этот README после проверки. Сейчас файлы `docs/` находятся в рабочем дереве как новые и перед передачей их надо явно добавить в Git, если они должны войти в поставку.

### `local_ui/`

- `local_ui/README.md` — запуск, UI, streaming, artifacts и troubleshooting.
- `local_ui/langgraph.json` — graph id -> Python export.
- `local_ui/install.ps1` — offline install archive с SHA256 и atomic replace.
- `local_ui/deep-agents-ui.local.patch` — изменения официального Deep Agents UI под threads, subagents и Files panel.

### `scripts/`

- `scripts/README.md` — описание служебных scripts.
- `scripts/build_ui_archive.sh` — пересборка Linux offline UI archive, parts и checksum.
- `scripts/check_project_quality.py` — AST/docstring/размер Python-файлов.

### `skills/`

- `skills/README.md` — правила организации skills.
- `skills/average-transaction-by-rule/SKILL.md` — сценарий расчёта транзакций по правилу.
- `skills/average-transaction-by-rule/README.md` — подробности сценария.
- `skills/cards-event-table/SKILL.md` — карточка источника cards.
- `skills/cards-event-table/README.md` — описание cards.
- `skills/cards-event-table/fields.md` — поля cards.
- `skills/convert-data-structures/SKILL.md` — преобразования pandas/NumPy/PySpark.
- `skills/hit-table/SKILL.md` — карточка hits.
- `skills/hit-table/README.md` — описание hits.
- `skills/hit-table/fields.md` — поля hits.
- `skills/hit-table/joins.md` — связи hits.
- `skills/poisk-zapisey-po-opisaniyu/SKILL.md` — сценарий смыслового поиска точных значений.
- `skills/poisk-zapisey-po-opisaniyu/README.md` — подробности поиска.
- `skills/refactor-create-files/SKILL.md` — создание/рефакторинг файлов и notebook.
- `skills/table-data-retrieval-workflow/SKILL.md` — общий workflow табличной выгрузки.
- `skills/uko-event-table/SKILL.md` — карточка uko.
- `skills/uko-event-table/README.md` — описание uko.
- `skills/uko-event-table/fields.md` — поля uko.

### Runtime/generated, не коммитятся

- `.venv/` — Python environment.
- `.deep_agent/memory/` — user profile.
- `.deep_agent/review_snapshots/` — snapshots review.
- `.deep_agent/notebook_scripts/` — notebook cache.
- `artifacts/` — JSONL и пользовательские результаты.
- `debug_prompts/` — prompt logs; сейчас каталог не добавлен в `.gitignore`, это стоит учесть перед коммитом.
- `local_ui/.runtime/` — распакованный frontend и backend logs.
- `.idea/`, `__pycache__/`, caches linters — локальные файлы разработки.

## Проверки перед передачей

В репозитории сейчас нет набора unit/integration tests: нет `tests/`, pytest config, mock Spark или local Spark fixture. Единственная автоматическая проверка проекта — статический quality script.

Минимум перед коммитом:

```powershell
python scripts/check_project_quality.py
python -m compileall deep_agent user_config run_ui.py
```

Для изменения Spark отдельно проверяю:

1. parser на корректном query и ошибке периода;
2. создание и остановку session;
3. `count` и JSONL write;
4. cancel при исключении;
5. чтение полного JSONL через `python`;
6. первый запрос с отсутствующим user profile;
7. параллельный сценарий profile/load_data, если менялся lifecycle.

Для изменения tools/middleware проверяю итоговый `debug_prompts/*.json`: имя, args schema, description и видимость для каждой роли. Для UI — thread switching, streaming subagents, nested tool calls и Files panel.

## Известные ограничения и технический долг

- `create_spark_session()` привязан к конкретным путям и YARN/HDFS-конфигурации.
- `sqlalchemy` нужен опциональному PostgreSQL request logger, но не объявлен dependency.
- `getOrCreate()` плюс обязательный `stop()` опасен для shared SparkSession.
- Profile Spark lifecycle не использует lock/active-session registry `load_data`.
- `load_data` сериализован process-wide lock и не выполняется параллельно в одном процессе.
- Login профиля извлекается из чисел в workspace path; на обычном локальном пути без login сборка profile reference может завершиться ошибкой.
- Prompt-only скрытие tools не является настоящим разрешением доступа.
- Добавление Python-файла в `tools/` или `middleware/` ничего не регистрирует автоматически.
- Data-agent не имеет shell, но его filesystem backend по-прежнему умеет писать файлы workspace.
- `python` не обеспечивает security isolation: policy фактически проверяет непустой код, а абсолютные пути вне workspace не отклоняются во всех сценариях.
- Shell tool не наследует env процесса; команды, рассчитывающие на внешние переменные, потребуют отдельной настройки.
- `debug_prompts/` может содержать рабочий контекст и сейчас не игнорируется Git.
- Автоматических тестов Spark lifecycle, tool visibility и middleware order нет.
- В description нативного `task` сейчас остаётся шаблон `{available_agents}`: middleware копирует строку без форматирования. Фактическое описание стоит проверить в prompt log и исправить отдельно.
- MCP dependency установлена, но MCP wiring в проекте отсутствует.
- Python lock-файла нет, а `deepagents` задан нижней границей версии. После обновления зависимостей нативный набор tools/middleware надо перепроверять.
- Полный offline UI archive после frontend-изменений надо пересобирать отдельно и обновлять `SHA256SUMS`/`.part*`.

Если коллега не уверен, где делать изменение, безопасный порядок такой: сначала определить роль, затем точку регистрации tool/middleware, после этого проверить фактический список tools в prompt log и только потом менять prompt. В этом проекте prompt не должен компенсировать неправильно выданный доступ или неподключённую реализацию.
