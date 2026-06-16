# Пошаговое изучение проекта для разработчика

Этот файл описывает маршрут изучения проекта `DeepAgent` с точки зрения разработки. Цель маршрута - понять проект на уровне, достаточном для уверенного изменения архитектуры, добавления tools, middlewares, subagents, skills и переносов в другие проекты.

## 1. Сначала пойми назначение проекта

Проект собирает аналитического агента поверх `deepagents` и LangChain/LangGraph. Агент получает пользовательский вопрос, выбирает релевантные доменные `SKILL.md`, вызывает специализированного subagent-а для чтения Spark-таблиц, при необходимости сохраняет большие результаты в pickle и может выполнять безопасный Python-код для анализа выгруженных данных.

Главная идея проекта: код отвечает за механику агента, а бизнес-смысл таблиц и правил живет в `deep_agent/skills`.

## 2. Изучи корневые файлы

Начни с файлов в корне проекта:

- `run.py` - минимальный сценарий запуска: Spark session, settings, data tools, сборка агента, один `invoke`.
- `model.py` - подключение chat model. В этом файле нельзя запускать проверки с реальными API-ключами без явного разрешения.
- `pyproject.toml` - конфигурация Python-пакета, pytest, ruff и package-data.
- `deep_agent/requirements.txt` - зависимости runtime.
- `deep_agent/README.md` - пользовательская документация и обзор возможностей.

Контрольная точка: после этого ты должен уметь словами объяснить, что происходит при `python run.py`.

## 3. Разбери публичный API пакета

Открой `deep_agent/agent.py`, `deep_agent/settings.py` и README тематических папок.

Зафиксируй публичные функции:

- `build_analytics_deep_agent` - основная сборка агента.
- `build_spark_data_tools` - сборка `read_table` поверх Spark session.
- `load_deep_agent_settings` - загрузка настроек.
- `build_data_tools` - сборка data-tools через фабрику из конфига.

Контрольная точка: ты должен понимать, какие функции должен импортировать внешний проект, а какие модули являются внутренними деталями.

## 4. Пройди главный поток запуска

Изучи `run.py` построчно:

1. Создается `SparkSession`.
2. Загружаются `DeepAgentSettings`.
3. Создается список tools чтения данных через `build_spark_data_tools(spark, query_parser_model=model)`.
4. Собирается граф через `build_analytics_deep_agent(...)`.
5. Выполняется `agent.invoke(...)`.
6. Из результата достается последнее сообщение.

Контрольная точка: ты должен уметь заменить `USER_MESSAGE`, подставить другую модель и объяснить, почему `thread_id` и `recursion_limit` передаются через config.

## 5. Изучи конфигурацию

Файлы:

- `deep_agent/settings.py`
- `deep_agent/config/defaults.json`

Разбери поля `DeepAgentSettings`:

- `skills_root` и `skills_virtual_dir` - где лежат skills и как их видит DeepAgents.
- `tool_outputs_dir` - куда сохраняются большие результаты.
- `tool_output_*` - пороги offload.
- `context_edit_*` - очистка старых tool results из контекста.
- `max_tool_calls_per_run` - общий бюджет tool-вызовов одного запуска.
- `max_model_retries` - число повторов model call.
- `max_subagent_model_calls` - лимит ходов subagent-а.

Контрольная точка: ты должен уметь создать override JSON и подключить его через `DEEP_AGENT_CONFIG_PATH`.

## 6. Разбери сборку агента

Главный файл:

- `deep_agent/agent.py`

Иди по функции `build_analytics_deep_agent` строго по шагам в комментариях:

1. Settings.
2. Data tools.
3. Middleware.
4. Backend.
5. Subagents.
6. Custom tools supervisor-а.
7. `create_deep_agent`.

Особенно важно понять, что `data_tools` передаются не напрямую, а через `wrap_data_tools_with_query_code`. Это добавляет к результату прозрачное описание запроса и metadata, которые дальше используются offload-механикой и reasoning-ом агента.

Контрольная точка: ты должен уметь нарисовать цепочку `run.py -> build_analytics_deep_agent -> create_deep_agent`.

## 7. Изучи prompts как контракт поведения

Файл:

- `deep_agent/prompts/`

Раздели prompts по ролям:

- `SYSTEM_PROMPT` - поведение supervisor-а.
- `DATA_RETRIEVAL_PROMPT` - поведение subagent-а чтения данных.
- prompts для skills context.
- `tool_contracts.py` - descriptions встроенных tools без добавления правил в system prompts.

Правило разработки: system prompts описывают роль и общий процесс агента. Доступность, параметры и правила применения
tools описываются только в descriptions инструментов. Доменные знания о таблицах хранятся в `deep_agent/skills`.

Контрольная точка: ты должен понимать, что менять в prompts, а что выносить в skills.

## 8. Изучи state

Файл:

- `deep_agent/state.py`

Разбери:

- `AnalyticsAgentState` - расширение состояния агента.
- `extract_state_messages` - безопасное извлечение сообщений из разных представлений state.

Этот модуль маленький, но важный: middlewares используют его, чтобы не зависеть от одного конкретного формата state.

Контрольная точка: ты должен понимать, почему middleware не должны напрямую предполагать один формат state.

## 9. Изучи subagents

Файл:

- `deep_agent/subagents/`

Разбери:

- как собирается spec `data-retrieval-agent`;
- какие tools и middleware получает subagent;
- почему subagent сам проверяет отчёт по skills и tool outputs перед возвратом supervisor-у.

Контрольная точка: ты должен уметь объяснить границу ответственности supervisor-а и data-retrieval-agent.

## 10. Изучи инструмент чтения данных

Файл:

- `deep_agent/tools/spark_data.py`

Начни с `ReadTableInput` и `build_spark_data_tools`, затем переходи к `_read_table`.

Важно понять поддерживаемый DSL:

- `select_columns`: `col1, col2`
- `filters`: `event_dt between 20260101,20260131; epk_id eq 123`
- `derived_columns`: `event_month = year_month(event_dt)`
- `group_by`: `event_description`
- `aggregations`: `count(event_id) as events_count`
- `order_by`: `events_count desc`

Дальше изучи helper-функции парсинга:

- `_split_items`
- `_parse_filter_item`
- `_parse_derived_item`
- `_parse_aggregation_item`
- `_parse_order_item`
- `_parse_scalar`

Контрольная точка: ты должен уметь добавить новый оператор фильтра или новую функцию derived column без ломки существующего DSL.

## 11. Изучи wrapper data-tools

Файл:

- `deep_agent/data/result_wrapper.py`

Этот модуль оборачивает tools чтения данных и добавляет прозрачность:

- SQL-подобное описание запроса.
- Количество строк.
- Нормализацию результата.
- Подготовку artifact-а с rows.

Контрольная точка: ты должен понимать, почему агенту полезно видеть не только строки результата, но и сгенерированное описание запроса.

## 12. Изучи offload больших результатов

Файл:

- `deep_agent/middleware/tool_output_file.py`

Разбери поток:

1. Middleware перехватывает `ToolMessage`.
2. Пытается извлечь табличный payload.
3. Если результат большой, пишет rows в `.pkl`.
4. В контекст возвращает короткое описание, путь к файлу и preview.

Особое внимание:

- `_extract_tabular_payload`
- `_extract_rows_from_value`
- `_write_rows_to_pkl`
- `_build_file_summary`
- `_build_inline_saved_file_note`

Контрольная точка: ты должен уметь изменить пороги offload через config, не меняя код.

## 13. Изучи Python sandbox

Файлы:

- `deep_agent/runtime/python_sandbox.py`
- `deep_agent/tools/python_execution.py`

`python_sandbox.py` создает persistent namespace и helpers:

- `read_pickle_file`
- `describe_pickle_file`
- `rows_to_dataframe`
- `pd`
- `np`
- пути проекта и tool outputs.

`execute_python_code.py` отвечает за:

- нормализацию кода;
- проверку политики безопасности;
- выполнение кода в sandbox;
- JSON-ответ с preview, stdout/stderr и traceback.

Контрольная точка: ты должен понимать, почему запрещены `eval`, `exec`, shell-вызовы и удаление файлов.

## 14. Изучи skills context

Файлы:

- `deep_agent/middleware/skills_context.py`
- `deep_agent/tools/skill_loader.py`
- `deep_agent/skills/**/SKILL.md`

Порядок изучения:

1. `discover_skill_context_files` - как находятся skills.
2. `build_skills_index` - как строится индекс skills.
3. `select_relevant_skill_paths_with_llm` - как модель выбирает релевантные skills.
4. Нативный `SkillsMiddleware` - как frontmatter skills добавляется в system prompt.
5. `read_file` - как полный `SKILL.md` загружается по progressive disclosure.

Контрольная точка: ты должен уметь добавить новый `SKILL.md`, чтобы агент начал использовать новое доменное правило без изменения Python-кода.

## 15. Изучи защитные middleware

Файлы:

- `deep_agent/middleware/tool_loop_guard.py`
- `deep_agent/middleware/tool_visibility.py`
- `deep_agent/middleware/tool_descriptions.py`

`ToolCallLimitMiddleware` ограничивает общий бюджет вызовов tools.

Разделение tools обеспечивается отдельными compiled subagents и backend: coding-agent
получает workspace shell, data-agent и supervisor работают без shell.

Descriptions встроенных tools задаются через `HarnessProfile.tool_description_overrides`.

Контрольная точка: ты должен понимать, какие проблемы решаются allowlist tools, лимитами tool calls, model calls и recursion limit.

## 16. Изучи контракт доступных tools

Вернись в:

- `deep_agent/agent.py`
- `deep_agent/prompts/`

Сопоставь `SUPERVISOR_TOOL_NAMES`, `DATA_RETRIEVAL_TOOL_NAMES` и prompt-блоки обеих ролей.

Контрольная точка: список реально видимых tools и текст prompt должны совпадать.

## 17. Изучи backend

Вернись в:

- `deep_agent/agent.py`

Разбери:

- `build_skills_backend`

Backend связывает виртуальные пути DeepAgents с локальными директориями:

- `/skills/` -> `deep_agent/skills`
- `/tool_outputs/` -> `runs/deep_agent_tool_outputs`

Контрольная точка: ты должен уметь объяснить разницу между локальным путем Windows и виртуальным путем, который видит агент.

## 18. Изучи модель расширения проекта

Типовые задачи расширения:

### Добавить новую таблицу

1. Добавь `deep_agent/skills/<table-name>/SKILL.md`.
2. Опиши назначение таблицы, ключевые поля, типовые фильтры и правила интерпретации.
3. Проверь, что `read_table` умеет выбрать нужные поля.
4. Код менять не нужно, если DSL уже покрывает сценарий.

### Добавить новый оператор фильтра

1. Обнови описание `READ_TABLE_DESCRIPTION`.
2. Добавь оператор в `_FILTER_OPERATORS`.
3. Реализуй ветку в `_build_filter_expression`.
4. Добавь пример в README или skill, если оператор доменно важен.

### Добавить новый derived operation

1. Добавь имя операции в `_DERIVED_OPERATIONS`.
2. Реализуй ветку в `_build_derived_column`.
3. Обнови описание tool.

### Добавить новый custom tool supervisor-а

1. Создай файл в `deep_agent/tools`.
2. Добавь BaseModel-схему с docstring.
3. Добавь фабрику `build_<tool_name>_tool`.
4. Подключи tool в шаге 6 `build_analytics_deep_agent`.
5. Экспортируй из `tools/__init__.py`, если tool должен быть публичным.

### Добавить новый subagent

1. Добавь имя и схемы в `agent_specs.py`.
2. Добавь prompt в `prompts.py`.
3. Добавь отдельный builder-модуль в `deep_agent/subagents` и зарегистрируй его в `registry.py`.
4. Подключи spec в `build_analytics_subagent_specs`.

## 19. Изучи правила качества кода проекта

В проекте важно соблюдать локальные правила:

- В начале каждого Python-файла должен быть docstring с перечислением функций и классов.
- Все функции и классы должны иметь docstring на русском языке с описанием входных и выходных данных.
- Pydantic/BaseModel-схемы должны иметь docstring.
- Не добавляй абстракции заранее.
- Не зашивай доменные знания в код, если их можно выразить в `SKILL.md`.
- Не используй реальные API-ключи для проверок без явного разрешения.
- Не переписывай файлы целиком, если можно внести точечные изменения.

## 20. Рекомендуемый порядок практики

1. Запусти импортную проверку:

```bash
python -c "import deep_agent; print(deep_agent.__file__)"
```

2. Прочитай settings:

```bash
python -c "from deep_agent.settings import load_deep_agent_settings; print(load_deep_agent_settings())"
```

3. Проверь компиляцию:

```bash
python -m compileall deep_agent
```

4. Создай тестовый skill и убедись, что он появляется в индексе skills.

5. На тестовой Spark table проверь `read_table` с простым select.

6. Проверь фильтры, derived columns, aggregations и order_by.

7. Проверь offload: временно снизь пороги в override-конфиге и убедись, что `.pkl` создается.

8. Проверь `execute_python_code` на чтении созданного `.pkl`.

9. Проверь, что supervisor и data-retrieval-agent видят только свои allowlist tools.

10. Только после этого меняй архитектуру.

## 21. Ментальная модель всего проекта

Держи в голове такой поток:

```text
Пользовательский вопрос
  -> run.py
  -> build_analytics_deep_agent
  -> SkillsMiddleware показывает index, агент читает релевантный SKILL.md
  -> supervisor решает, нужен ли data-retrieval-agent
  -> data-retrieval-agent вызывает read_table
  -> data_tools_wrapper добавляет описание запроса
  -> ToolOutputFileMiddleware сохраняет большой результат в .pkl
  -> supervisor при необходимости вызывает execute_python_code
  -> итоговый ответ пользователю
```

## 22. Чеклист понимания на 100%

Ты хорошо знаешь проект, если можешь без подсказок:

- Объяснить, как `run.py` собирает агента.
- Назвать все обязательные поля `defaults.json`.
- Объяснить разницу между supervisor и data-retrieval-agent.
- Добавить новый skill без изменения Python-кода.
- Добавить новый оператор `read_table`.
- Объяснить, когда результат tool уходит в pickle.
- Прочитать `.pkl` через `execute_python_code`.
- Объяснить, как работает shared selection skills между supervisor и subagent.
- Настроить разные allowlist tools для supervisor-а и data-retrieval-agent.
- Подключить другую фабрику data-tools через config.
- Найти место, где нужно менять prompts.
- Найти место, где настраивается backend виртуальных путей.
- Выполнить базовые проверки без использования API-ключей.
