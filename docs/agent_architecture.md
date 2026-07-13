# Архитектура DeepAgent

## Сборка

```mermaid
flowchart TB
    UI["run_ui.py / LangGraph Agent Server"] --> Adapter["user_config/langgraph_agent_server.py"]
    Adapter --> Model["KitAI chat model"]
    Adapter --> SparkTool["build_spark_data_tools"]
    Adapter --> Build["build_agent"]
    Model --> Build
    SparkTool --> Build
    Build --> Context["_AgentBuildContext"]
    Context --> Backends["shell backend: supervisor/coding<br/>filesystem backend: data"]
    Context --> Tools["project tools"]
    Context --> Skills["skills selector + load_skills"]
    Backends --> Coding["compiled coding-agent"]
    Backends --> Data["compiled data-retrieval-agent"]
    Tools --> Coding
    Tools --> Data
    Coding --> Supervisor["compiled supervisor"]
    Data --> Supervisor
```

`_register_deepagents_profile()` отключает базовый prompt и автоматический
`general-purpose` subagent внешней библиотеки. В graph остаются только явно
собранные `coding-agent` и `data-retrieval-agent`.

## Роли и доступ

| Роль | Project tools | Backend |
| --- | --- | --- |
| Supervisor | `load_skills`, `python`, `get_project_structure`, внешние `supervisor_tools` | `Utf8LocalShellBackend` |
| coding-agent | `load_skills`, `python`, `get_project_structure`, `convert_jupyter_notebook`, `review_refactor` | `Utf8LocalShellBackend` |
| data-retrieval-agent | `data_tools`, `load_skills`, `python` | `Utf8FilesystemBackend` |

`edit_file` скрыт от всех трёх ролей только на уровне prompt. Это не security
boundary. Data-agent не имеет рабочего shell backend, но filesystem tools остаются.

## Skills

Supervisor строит компактный index всех `SKILL.md`, отдельным structured-output
вызовом выбирает релевантные файлы и полностью добавляет их в system message.
Data-agent читает тот же выбор через общий `shared_selection`. Coding-agent при
необходимости вызывает `load_skills` сам. Нативный каталог skills DeepAgents не
подключён, чтобы один и тот же список не попадал в prompt вторым способом.

## Spark

```mermaid
flowchart LR
    Q["load_data(query)"] --> Parser["LLM parser<br/>ParsedDataQuery"]
    Parser --> Session["_managed_spark_session"]
    Session --> Transform["Spark DataFrame transformations"]
    Transform --> Count["count + progress"]
    Count --> Jsonl["Spark writer → JSON parts → один JSONL"]
    Jsonl --> Result["path, rows, columns, preview"]
    Result --> Stop["cancel jobs при ошибке + spark.stop"]
```

Текущая SQL-like/LLM/Spark execution-логика сохранена. HITL удалён: запрос не
останавливается на approval. Полный результат сохраняет сам `load_data`; отдельного
PKL-offload middleware больше нет.

## Memory и persistence

Все роли читают `AGENTS.md` через `MemoryMiddleware`. Если data-tool содержит
`spark_session_factory` в metadata, supervisor дополнительно создаёт и читает
`/.deep_agent/memory/user_profile.md`.

При прямом вызове `build_agent` используется `InMemorySaver`. UI adapter передаёт
`checkpointer=None`, потому что persistence threads предоставляет Agent Server.
Локальный runtime `langgraph dev` периодически сохраняет threads, runs, store и checkpoints
в `<cwd>/.langgraph_api/*.pckl`, а при следующем запуске загружает их обратно. Launcher задаёт
`cwd` равным корню проекта, поэтому история UI переживает полный перезапуск приложения.

## Артефакты

- `artifacts/*.jsonl` — полный результат Spark `load_data`;
- `.deep_agent/memory/` — профиль пользователя;
- `.deep_agent/review_snapshots/` — исходные версии файлов для review;
- `.deep_agent/notebook_scripts/` — служебные notebook scripts;
- `debug_prompts/*.json` — фактические model requests.
