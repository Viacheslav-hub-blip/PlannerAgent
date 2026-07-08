# Deep Agent

Основной путь запуска для локального интерфейса

```text
run_ui.py
  -> local_ui/langgraph.json
  -> user_config/langgraph_agent_server.py:agent
  -> build_langgraph_agent_server_agent()
  -> deep_agent.agent.build_agent(...)
  -> deep_agent.agent_graph_builder
  -> supervisor
  -> coding-agent
  -> data-retrieval-agent
```


1 `run_ui.py` проверяет окружение, запускает LangGraph Agent Server и локальный
   интерфейс.
2 `local_ui/langgraph.json` говорит Agent Server, что граф агента лежит в
  `user_config/langgraph_agent_server.py` в переменной `agent`.
3 `user_config/langgraph_agent_server.py` собирает настройки, модель,
   `load_data`, логирование запросов и вызывает `build_agent(...)`.
4 `build_agent(...)` собирает главного агента, подагентов, тулы, prompts,
   middleware, файловый доступ и память диалога.


## Агенты

В проекте есть главный агент и два подагента.

| Агент | Где задан | Что делает |
| --- | --- | --- |
| `supervisor` | `deep_agent/agent_graph_builder.py` в `_build_supervisor_graph` | Принимает запрос пользователя, выбирает план, вызывает тулы и делегирует крупные задачи подагентам. |
| `coding-agent` | `deep_agent/agent_graph_builder.py` в `_build_coding_agent_graph` и `deep_agent/subagents.py` | Работает с кодом, файлами, расчетами, notebook-файлами и проверками. |
| `data-retrieval-agent` | `deep_agent/agent_graph_builder.py` в `_build_data_retrieval_agent_graph` и `deep_agent/subagents.py` | Читает таблицы, подтверждает источники, выгружает данные и сохраняет результат в файл. |

Имена и описания подагентов меняются в `deep_agent/subagents.py`:

- `CODING_AGENT_NAME`;
- `CODING_AGENT_DESCRIPTION`;
- `DATA_RETRIEVAL_AGENT_NAME`;
- `DATA_RETRIEVAL_AGENT_DESCRIPTION`.

## Где теперь менять поведение агента

Я держу поведение в понятных местах:

- главный prompt меняю в `deep_agent/prompts/supervisor_prompt.py`;
- prompt `coding-agent` меняю в `deep_agent/prompts/coding_agent_prompt.py`;
- prompt `data-retrieval-agent` меняю в
  `deep_agent/prompts/data_retrieval_agent_prompt.py`;
- имена и описания подагентов меняю в `deep_agent/subagents.py`;
- доменные правила, таблицы, поля и сценарии работы меняю в `skills/`;
- описания своих тулов меняю рядом с кодом тула;
- описания встроенных тулов DeepAgents меняю в
  `deep_agent/prompts/tool_description_prompt.py`.

Как сейчас собирается текст:

1. `supervisor` получает `SYSTEM_PROMPT`.
2. Если я явно передал `system_prompt_suffix` в `build_agent(...)`, он
   добавляется в конец `SYSTEM_PROMPT`.
3. `coding-agent` получает только `CODING_AGENT_PROMPT`.
4. `data-retrieval-agent` получает только `DATA_RETRIEVAL_PROMPT`.
5. `PreloadedSkillsContextMiddleware` добавляет выбранные `SKILL.md`.
6. `PromptToolDescriptionsMiddleware` подставляет описания встроенных тулов из
   `TOOL_DESCRIPTION_OVERRIDES`.

Старые слои удалены и не участвуют в поведении:

- отдельного файла для добавочного GigaChat prompt больше нет;
- отдельного файла для регистрации профиля DeepAgents больше нет;
- отдельный профиль DeepAgents не регистрируется;
- штатный `general-purpose` включается самим DeepAgents.


### Где лежат тулы

Основные тулы лежат в `deep_agent/tools/`.

| Тул | Файл | Имя задано здесь | Описание задано здесь | Входная схема |
| --- | --- | --- | --- | --- |
| `load_data` | `deep_agent/tools/load_data_spark_tool.py` | `StructuredTool.from_function(name="load_data")` | `READ_TABLE_DESCRIPTION` | `ReadTableInput` в `deep_agent/data_processing/load_data_query_models.py` |
| `python` | `deep_agent/tools/python_execution_tool.py` | `PYTHON_TOOL_NAME` | `PYTHON_TOOL_DESCRIPTION` | `PythonInput` |
| `load_skills` | `deep_agent/tools/skill_loader_tool.py` | `LOAD_SKILLS_TOOL_NAME` | `LOAD_SKILLS_DESCRIPTION` | аргументы функции `load_skills(...)` |
| `get_project_structure` | `deep_agent/tools/project_structure_tool.py` | `GET_PROJECT_STRUCTURE_TOOL_NAME` | `GET_PROJECT_STRUCTURE_DESCRIPTION` | `GetProjectStructureInput` |
| `convert_jupyter_notebook` | `deep_agent/tools/jupyter_notebook_tool.py` | `CONVERT_JUPYTER_NOTEBOOK_TOOL_NAME` | `CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION` | `ConvertJupyterNotebookInput` |
| `review_refactor` | `deep_agent/tools/refactor_review_tool.py` | `REVIEW_REFACTOR_TOOL_NAME` | `REVIEW_REFACTOR_TOOL_DESCRIPTION` | `ReviewRefactorInput` |

Часть встроенных тулов приходит из DeepAgents. Например:

- `write_todos`;
- `task`;
- `ls`;
- `read_file`;
- `write_file`;
- `edit_file`;
- `glob`;
- `grep`;
- `execute`.

Но их описания переопределяю в `deep_agent/prompts/tool_description_prompt.py`.

### Какие тулы видит каждый агент

Списки тулов собираются в `deep_agent/agent_graph_builder.py`.

| Агент | Где список | Что видит |
| --- | --- | --- |
| `supervisor` | `_build_supervisor_graph` | `load_skills`, `python`, `get_project_structure`, все `supervisor_tools`, встроенные тулы DeepAgents |
| `coding-agent` | `_build_coding_agent_graph` | `load_skills`, `python`, `get_project_structure`, `convert_jupyter_notebook`, `review_refactor`, встроенные файловые тулы и `execute` |
| `data-retrieval-agent` | `_build_data_retrieval_agent_graph` | `load_data`, `load_skills`, `python`, встроенные файловые тулы без shell-доступа |

Сейчас `edit_file` скрыт от `supervisor` и `coding-agent` через `hidden_tool_names`.

### Как я открываю тул для агента

Если я хочу открыть уже существующий тул для агента, я меняю список в
`deep_agent/agent_graph_builder.py`.

Пример: открыть `review_refactor` для главного агента.

```python
return create_deep_agent(
    model=context.model,
    tools=[
        tools.load_skills_tool,
        tools.python_tool,
        tools.project_structure_tool,
        tools.review_refactor_tool,
        *tools.supervisor_tools,
    ],
    ...
)
```

Пример: открыть новый data-тул для `data-retrieval-agent`.

```python
config = build_data_retrieval_subagent_config(
    model=context.model,
    data_tools=[
        *tools.data_tools,
        tools.load_skills_tool,
        tools.python_tool,
        tools.project_structure_tool,
    ],
    ...
)
```

- тулы для чтения данных я передаю через `data_tools`;
- тулы только для главного агента я передаю через `supervisor_tools`;
- тулы, которые являются частью ядра проекта, я собираю в `_build_agent_tools`.

### Скрытие тулов

Чтобы скрыть тул от модели, я добавляю его имя в `hidden_tool_names` при сборке
middleware.

Пример:

```python
middleware = _build_native_runtime_middleware(
    context.settings,
    tool_output_file_middleware,
    filesystem_backend=backends.coding,
    workspace_root=context.workspace_root,
    agent_name="coding-agent",
    limit_model_calls=True,
    hidden_tool_names=("edit_file", "execute"),
)
```

Скрытие делает `PromptToolFilterMiddleware` из
`deep_agent/middleware/tool_description_middleware.py`.

Для своих тулов я меняю описание рядом с кодом тула:

- `READ_TABLE_DESCRIPTION`;
- `PYTHON_TOOL_DESCRIPTION`;
- `LOAD_SKILLS_DESCRIPTION`;
- `GET_PROJECT_STRUCTURE_DESCRIPTION`;
- `CONVERT_JUPYTER_NOTEBOOK_DESCRIPTION`;
- `REVIEW_REFACTOR_TOOL_DESCRIPTION`.

Для встроенных тулов DeepAgents я меняю описание в
`deep_agent/prompts/tool_description_prompt.py`, в словаре
`TOOL_DESCRIPTION_OVERRIDES`.

Эти описания подставляет `PromptToolDescriptionsMiddleware` прямо перед вызовом
модели. Это единственное проектное место, где меняются описания встроенных
тулов.

### Как я меняю имя тула

Для тулов на `BaseTool` это поле `name`:

```python
class PythonTool(BaseTool):
    name: str = PYTHON_TOOL_NAME
```

Для тулов на `StructuredTool` это аргумент `name`:

```python
StructuredTool.from_function(
    func=read_table,
    name="load_data",
    description=READ_TABLE_DESCRIPTION,
    args_schema=ReadTableInput,
)
```

## Skills

`skills` - это папка с доменными знаниями и сценариями работы.

Обычно папка skill выглядит так:

```text
skills/
  hit-table/
    SKILL.md
    README.md
    fields.md
    joins.md
```

Что я кладу в файлы:

- `SKILL.md` - короткая карточка. В ней только то, что нужно для выбора skill:
  когда использовать, какой источник, важные поля, главные ограничения.
- `README.md` - подробное описание источника или сценария для человека.
- `fields.md` - полный список полей таблицы или источника.
- `joins.md` - правила связей с другими источниками.

### Как агент выбирает skills

Выбор делает `PreloadedSkillsContextMiddleware` из
`deep_agent/middleware/skills_context_middleware.py`.

Порядок такой:

1. Middleware ищет все файлы `SKILL.md` внутри папки `skills`.
2. Из каждого `SKILL.md` читает `name` и `description`.
3. Передает этот список модели выбора.
4. Модель выбирает нужные пути `SKILL.md`.
5. Middleware загружает выбранные `SKILL.md` в системный prompt.
6. Подагенты получают тот же выбранный набор через общий кэш.

Если агенту позже нужен еще один skill, он вызывает тул `load_skills`.

### Как работает `load_skills`

Тул `load_skills` лежит в `deep_agent/tools/skill_loader_tool.py`.

Он принимает:

- `skill_names` - имена skills или пути через запятую;
- `already_loaded` - skills, которые не нужно грузить повторно.

Пример:

```text
load_skills(
  skill_names="hit-table, cards-event-table",
  already_loaded=""
)
```

Тул умеет искать skill по:

- имени из `name`;
- имени папки;
- относительному пути;
- workspace-пути вида `/skills/hit-table/SKILL.md`.

## Настройки KitAI
Пример:

```python
KITAI_MODEL_CONFIG = {
    "kitai_host_sdk": "https://kitai.example",
    "cert_file": "C:/absolute/path/client.crt",
    "key_file": "C:/absolute/path/client.key",
    "model": "GigaChat-2-Max",
    "temperature": 0.05,
}
```

## Карта файлов проекта

Ниже я описываю проектные файлы. Я не описываю `.venv`, `.idea`,
`local_ui/.runtime`, кэши и временные артефакты.

### Корень проекта

- `AGENTS.md` - правила поведения агента внутри этого проекта: как выбирать
  skills, когда делегировать задачи, как работать с данными и кодом.
- `run_ui.py` - основной скрипт запуска локального интерфейса. Проверяет окружение,
  запускает Agent Server и интерфейс.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part001` - первая часть архива
  интерфейса для запуска без сети.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part002` - вторая часть архива
  интерфейса.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part003` - третья часть архива
  интерфейса.

### `user_config/`

- `user_config/langgraph_agent_server.py` - адаптер для LangGraph Agent Server.
  Здесь я задаю `KITAI_MODEL_CONFIG`, собираю настройки UI, создаю Spark session,
  создаю `load_data`, подключаю логирование запросов и экспортирую переменную
  `agent`.

### `deep_agent/`

- `deep_agent/__init__.py` - объявляет пакет `deep_agent`.
- `deep_agent/_request_log_config.py` - собирает логгер пользовательских запросов
- `deep_agent/agent.py` - главная публичная точка сборки агента. Здесь находится
  `build_agent(...)`, сборка файлового доступа, памяти, путей и общего middleware.
- `deep_agent/agent_graph_builder.py` - пошаговая сборка графа: настройки, тулы,
  prompts, middleware, подагенты и главный агент.
- `deep_agent/agent_settings.py` - настройки по умолчанию: пути, лимиты, папка
  skills, папка артефактов, лимиты вызовов и функции преобразования workspace-путей.
- `deep_agent/agent_state.py` - схема state агента с приватными полями для
  предзагруженных skills.
- `deep_agent/gigachat_kitai_model.py` - адаптер KitAI-модели к интерфейсу
  LangChain messages и DeepAgents.
- `deep_agent/subagents.py` - имена, описания и конфигурации `coding-agent` и
  `data-retrieval-agent`.

### `deep_agent/data_processing/`

- `deep_agent/data_processing/__init__.py` - объявляет пакет обработки данных.
- `deep_agent/data_processing/load_data_query_models.py` - Pydantic-схемы для
  `load_data`: фильтры, вычисляемые колонки, агрегации, сортировка и входной
  запрос.
- `deep_agent/data_processing/load_data_query_parser.py` - разбирает SQL-похожий
  текст `query` через LLM в структурированные аргументы для `load_data`.
- `deep_agent/data_processing/load_data_query_values.py` - разбирает и проверяет
  текстовые значения колонок, фильтров, агрегаций и сортировок.
- `deep_agent/data_processing/load_data_result.py` - оборачивает data-тулы так,
  чтобы в результате было видно, какой запрос был выполнен.
- `deep_agent/data_processing/load_data_spark_execution.py` - выполняет Spark
  action, сохраняет результат в JSONL и готовит пример результата для ответа агента.
- `deep_agent/data_processing/load_data_spark_query.py` - строит и применяет
  PySpark-запрос: таблица, фильтры, вычисляемые колонки, группировки, сортировка.

### `deep_agent/execution/`

- `deep_agent/execution/filesystem_backend.py` - файловый доступ и shell-доступ с
  UTF-8 fallback, проверкой путей и поддержкой workspace paths.
- `deep_agent/execution/python_sandbox.py` - постоянная Python-среда для тула
  `python`, общие переменные и helper-функции.
- `deep_agent/execution/trace_logger.py` - запись шагов агента в человекочитаемый
  txt-файл.

### `deep_agent/middleware/`

- `deep_agent/middleware/README.md` - краткая карта middleware.
- `deep_agent/middleware/__init__.py` - объявляет пакет middleware.
- `deep_agent/middleware/filesystem_path_middleware.py` - нормализует пути для
  файловых тулов и добавляет проверенное описание файловых операций.
- `deep_agent/middleware/gigachat_runtime_middleware.py` - добавляет устойчивость
  для GigaChat: `think`, защиту shell-команд и остановку повторяющихся циклов.
- `deep_agent/middleware/model_error_middleware.py` - определяет временные ошибки
  модели, форматирует безопасное сообщение и скрывает чувствительные данные.
- `deep_agent/middleware/request_logging_middleware.py` - пишет пользовательские
  запросы в PostgreSQL, если логирование включено.
- `deep_agent/middleware/skills_context_middleware.py` - выбирает и предзагружает
  релевантные `SKILL.md`.
- `deep_agent/middleware/todo_reset_middleware.py` - сбрасывает todo state между
  пользовательскими запросами.
- `deep_agent/middleware/tool_context_middleware.py` - добавляет понятные подсказки
  к результатам тулов и ошибкам тулов.
- `deep_agent/middleware/tool_description_middleware.py` - меняет описания тулов
  перед вызовом модели и скрывает выбранные тулы.
- `deep_agent/middleware/tool_output_file_middleware.py` - сохраняет большие
  табличные результаты в pickle-файлы и оставляет в контексте короткий пример результата.

### `deep_agent/prompts/`

- `deep_agent/prompts/README.md` - краткая карта prompt-файлов.
- `deep_agent/prompts/__init__.py` - объявляет пакет prompts.
- `deep_agent/prompts/coding_agent_prompt.py` - системная инструкция для
  `coding-agent`.
- `deep_agent/prompts/data_retrieval_agent_prompt.py` - системная инструкция для
  `data-retrieval-agent`.
- `deep_agent/prompts/load_data_query_parser_prompt.py` - prompt для разбора
  SQL-похожего запроса `load_data`.
- `deep_agent/prompts/refactor_review_prompt.py` - prompt для внутренней проверки
  результата рефакторинга.
- `deep_agent/prompts/skills_context_prompt.py` - шаблоны текста, в который
  вставляются предзагруженные skills.
- `deep_agent/prompts/supervisor_prompt.py` - системная инструкция главного
  агента.
- `deep_agent/prompts/tool_description_prompt.py` - описания встроенных тулов,
  которые модель видит перед вызовом.

### `deep_agent/tools/`

- `deep_agent/tools/README.md` - краткая карта тулов.
- `deep_agent/tools/__init__.py` - объявляет пакет tools.
- `deep_agent/tools/jupyter_notebook_formatting.py` - форматирует ячейки notebook
  при конвертации `.py` и `.ipynb`.
- `deep_agent/tools/jupyter_notebook_tool.py` - тул `convert_jupyter_notebook` для
  конвертации `.py` в `.ipynb` и обратно.
- `deep_agent/tools/load_data_spark_tool.py` - тул `load_data` для чтения Spark
  таблиц, сохранения результата и короткого примера результата.
- `deep_agent/tools/project_structure_tool.py` - тул `get_project_structure` для
  краткого просмотра структуры проекта.
- `deep_agent/tools/python_execution_helpers.py` - helper-функции для `python`:
  преобразование workspace-путей и короткий показ артефактов.
- `deep_agent/tools/python_execution_tool.py` - тул `python`, постоянный Python REPL
  для расчетов и работы с файлами.
- `deep_agent/tools/refactor_review_tool.py` - тул `review_refactor` для локальной
  проверки результата рефакторинга.
- `deep_agent/tools/skill_loader_tool.py` - тул `load_skills` для дозагрузки
  выбранных `SKILL.md`.

### `local_ui/`

- `local_ui/README.md` - подробная инструкция по локальному интерфейсу.
- `local_ui/deep-agents-ui.local.patch` - локальный patch интерфейса Deep Agents UI
  под этот проект.
- `local_ui/install.ps1` - устанавливает подготовленный интерфейс из локального
  архива, проверяет SHA256 и распаковывает файлы.
- `local_ui/langgraph.json` - конфигурация LangGraph Agent Server. Указывает на
  `user_config/langgraph_agent_server.py:agent`.
- `local_ui/start.ps1` - устаревшая обертка запуска. Сейчас основной запуск -
  `python run_ui.py`.

### `scripts/`

- `scripts/README.md` - краткое описание служебных скриптов.
- `scripts/build_ui_archive.sh` - собирает архив интерфейса для запуска без сети и
  обновляет `.part*` и `SHA256SUMS`.
- `scripts/check_project_quality.py` - статическая проверка структуры Python-файлов:
  docstring файла, docstring функций и классов, базовые правила качества.

### `skills/`

- `skills/README.md` - общие правила устройства skills.
- `skills/average-transaction-by-rule/SKILL.md` - skill для расчета количества
  сработок и сумм транзакций по правилу антифрода.
- `skills/average-transaction-by-rule/README.md` - подробное описание этого
  сценария расчета.
- `skills/cards-event-table/SKILL.md` - карточка источника `cards` для карточных
  операций.
- `skills/cards-event-table/README.md` - подробное описание источника `cards`.
- `skills/cards-event-table/fields.md` - список полей источника `cards`.
- `skills/convert-data-structures/SKILL.md` - skill для преобразования логики между
  pandas, NumPy и PySpark.
- `skills/hit-table/SKILL.md` - карточка источника `hits` со сработками антифрода.
- `skills/hit-table/README.md` - подробное описание источника `hits`.
- `skills/hit-table/fields.md` - список полей источника `hits`.
- `skills/hit-table/joins.md` - правила связи `hits` с другими источниками.
- `skills/poisk-zapisey-po-opisaniyu/SKILL.md` - skill для поиска точных значений
  текстовой колонки по смысловому описанию пользователя.
- `skills/poisk-zapisey-po-opisaniyu/README.md` - подробное описание сценария
  поиска текстовых значений.
- `skills/refactor-create-files/SKILL.md` - skill для создания и рефакторинга
  файлов кода и notebook-файлов.
- `skills/table-data-retrieval-workflow/SKILL.md` - сценарий работы с табличными
  запросами, выбором периода, таблиц и постановкой задач подагентам.
- `skills/uko-event-table/SKILL.md` - карточка источника `uko` для не карточного
  канала, ДБО, СБП, переводов и операций по счетам.
- `skills/uko-event-table/README.md` - подробное описание источника `uko`.
- `skills/uko-event-table/fields.md` - список полей источника `uko`.
