# Deep Agent

Аналитический DeepAgent для GigaChat KitAI, LangGraph Agent Server и локального
Deep Agents UI. Репозиторий рассчитан на развертывание в закрытой среде: код не
читает параметры модели из `.env`, не требует API-ключей для проверок качества и
может запускать UI из заранее подготовленного offline-архива.

## Что входит в проект

- `deep_agent/` - Python-пакет агента: сборка graph, state, settings, middleware,
  tools, обработка данных и prompt-модули.
- `adapters/` - адаптеры запуска. Основная точка для UI:
  `adapters/langgraph_agent_server.py`.
- `skills/` - доменные инструкции и справочники, которые автоматически выбираются
  middleware перед запуском агента.
- `local_ui/` - конфиг LangGraph Agent Server, PowerShell-скрипты и инструкция для
  локального Deep Agents UI.
- `scripts/` - служебные проверки проекта и сборка offline-архива UI.
- `deep-agents-ui-node20-linux-x86_64.tar.gz.part001..003` и `SHA256SUMS` -
  части offline-архива UI для Linux x86_64 / Node.js 20.

Локальные каталоги `.venv/`, `.idea/`, `.deep_agent/`, `local_ui/.runtime/`,
`artifacts/`, `.env` и логи не являются частью поставки и игнорируются Git.

## Требования

- Python 3.11+.
- Git.
- Для локального UI: Node.js 20 runtime внутри подготовленного frontend-архива.
- Для Spark-инструмента `load_data`: доступная PySpark-среда и рабочая фабрика
  `SparkSession` в `adapters/langgraph_agent_server.py`.
- Для KitAI-модели: корпоративные пакеты `sber-kitai-sdk-langchain` и
  `sber-kitai-sdk-py`, доступные из вашего package index.

## Быстрый старт на чистой машине

```powershell
git clone <repo-url> deepagent
cd deepagent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[kitai,data,analytics,ui]
```

Если Spark или аналитические библиотеки на машине не нужны, можно поставить только
минимальный набор для сборки агента:

```powershell
python -m pip install -e .[kitai,ui]
```

## Локальная конфигурация KitAI

Базовый adapter содержит пустые значения `kitai_host_sdk`, `cert_file` и `key_file`.
Для конкретной машины отредактируйте словарь `KITAI_MODEL_CONFIG` в
`adapters/langgraph_agent_server.py`:

```python
KITAI_MODEL_CONFIG = {
    "kitai_host_sdk": "https://kitai.example",
    "cert_file": "C:/absolute/path/client.crt",
    "key_file": "C:/absolute/path/client.key",
    "model": "GigaChat-2-Max",
    "temperature": 0.05,
}
```

Не коммитьте сертификаты, ключи, реальные DSN и локальные `.env`-файлы. Пути к
сертификатам в `KITAI_MODEL_CONFIG` должны указывать на файлы конкретной машины.

## Логирование запросов

Логирование пользовательских запросов в PostgreSQL отключено по умолчанию. Чтобы
включить его на машине пользователя, задайте переменные окружения:

```powershell
$env:DEEP_AGENT_REQUEST_LOGGING_ENABLED = "1"
$env:DEEP_AGENT_REQUEST_LOG_DSN = "postgresql+psycopg2://<user>:<password>@<host>:5432/<db>"
$env:DEEP_AGENT_REQUEST_LOG_SCHEMA = "user"
$env:DEEP_AGENT_REQUEST_LOG_TABLE = "agent_request_logs"
```

Без `DEEP_AGENT_REQUEST_LOG_DSN` агент запускается без request-логгера.

## Установка offline UI

В репозитории хранятся части архива `deep-agents-ui-node20-linux-x86_64.tar.gz`.
Полный `.tar.gz` не коммитится: `local_ui/install.ps1` соберет его из `.part001`,
`.part002`, `.part003`, проверит SHA256 и распакует frontend в
`local_ui/.runtime/deep-agents-ui`.

```powershell
powershell -ExecutionPolicy Bypass -File local_ui\install.ps1 -Force
```

Подготовленный архив содержит Linux x86_64 `node_modules` для Node.js 20. Для
серверного запуска используйте Linux/WSL-окружение. Если нужен native Windows
frontend, установите зависимости frontend отдельно в совместимой среде и передайте
путь через `--frontend-dir`.

## Запуск UI

```powershell
python run_ui.py
```

По умолчанию:

- UI: `http://127.0.0.1:3000`
- LangGraph Agent Server: `http://127.0.0.1:2024`
- Assistant ID: `analytics-agent`

Порты можно переопределить:

```powershell
python run_ui.py --agent-port 2124 --ui-port 3100
python run_ui.py --agent-host 127.0.0.1 --agent-port 5555 --ui-host 0.0.0.0 --ui-port 8042
```

Launcher не скачивает зависимости и не применяет patch. Он только проверяет готовое
окружение, запускает LangGraph Agent Server и frontend dev server. Логи backend
пишутся в `local_ui/.runtime/logs/agent-server-*.out.log` и
`local_ui/.runtime/logs/agent-server-*.err.log`.

## Запуск без UI

```python
from deep_agent.agent import build_agent
from deep_agent.agent_settings import load_agent_settings
from deep_agent.gigachat_kitai_model import build_gigachat_kitai_model

model = build_gigachat_kitai_model(
    kitai_host_sdk="https://kitai.example",
    cert_file="C:/absolute/path/client.crt",
    key_file="C:/absolute/path/client.key",
    model="GigaChat-2-Max",
    temperature=0.05,
)

agent = build_agent(
    model=model,
    settings=load_agent_settings(),
    data_tools=[],
)
```

Для подключения Spark-инструмента используйте
`deep_agent.tools.load_data_spark_tool.build_spark_data_tools(...)` и передайте
полученный список в `data_tools`.

## Проверки перед развертыванием

Эти команды не используют API-ключи и не вызывают внешнюю модель:

```powershell
python -m compileall -q deep_agent adapters scripts run_ui.py
python scripts\check_project_quality.py
```

Если в dev-среде установлен Ruff, можно дополнительно запустить:

```powershell
python -m ruff check deep_agent adapters scripts run_ui.py
```

## Обновление offline-архива UI

Сборка архива выполняется в Linux x86_64 или WSL и может скачать официальный Node.js
20 для воспроизводимой проверки frontend:

```powershell
wsl -d Ubuntu -- bash /mnt/c/path/to/deepagent/scripts/build_ui_archive.sh
```

После изменения frontend, patch, `package.json` или `yarn.lock` нужно пересобрать
архив, обновить `.part*` и `SHA256SUMS`.

## Что не нужно коммитить

- `.venv/`, `.deep_agent/`, `.idea/`
- `local_ui/.runtime/`
- `local_ui/.env`, `.env`, любые локальные env-файлы
- `artifacts/`, `__pycache__/`, `.ruff_cache/`, `.mypy_cache/`, `*.log`
- полный `deep-agents-ui-node20-linux-x86_64.tar.gz`

## Troubleshooting

- `Python-зависимости ... не установлены`: активируйте `.venv` и установите
  `python -m pip install -e .[kitai,data,analytics,ui]`.
- `Не найдена директория frontend`: выполните `local_ui\install.ps1 -Force` или
  передайте `--frontend-dir`.
- `Agent Server не открыл порт`: смотрите последние строки stdout/stderr logs в
  `local_ui/.runtime/logs`.
- Белая страница UI при старом сохраненном URL: очистите `localStorage` ключ
  `deep-agent-config` или откройте UI на host/port, которые напечатал launcher.
