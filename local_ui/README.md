# Локальный Deep Agents UI

Папка подключает текущий аналитический DeepAgent к официальному
[`langchain-ai/deep-agents-ui`](https://github.com/langchain-ai/deep-agents-ui)
через штатный LangGraph Agent Server.

## Что видно в UI

- план из встроенного `write_todos`;
- аргументы, статус и результат вызовов инструментов;
- запуск `task` и итоговый ответ subagent;
- lifecycle-статус каждого subagent (`pending`, `running`, `complete`, `error`);
- поток сообщений и вложенные tool calls каждого subagent;
- текстовые артефакты из `/artifacts/`;
- история threads и запросы на approval для `write_file`/`edit_file`.

Скрытая цепочка рассуждений модели не публикуется.

## Подготовка и запуск

Требования: Python 3.11+, Git и Node.js 20+. Виртуальное окружение `.venv` желательно,
но скрипт работает и с текущим `python`.

`run_ui.py` работает только с уже подготовленным окружением: он не устанавливает Python-
или Node.js-зависимости, не клонирует репозиторий и не применяет patch. Перед первым
запуском установите Python-зависимости и распакуйте подготовленный Linux frontend:

```powershell
python -m pip install -e .[data,analytics,ui]
powershell -ExecutionPolicy Bypass -File local_ui\install.ps1 -Force
```

`install.ps1` работает без сети. Он использует
`deep-agents-ui-node20-linux-x86_64.tar.gz` либо собирает его из файлов
`.part001`, `.part002`, ...; затем проверяет SHA256 по корневому `SHA256SUMS` и
атомарно устанавливает frontend в `local_ui/.runtime/deep-agents-ui`.

После подготовки:

```powershell
python run_ui.py
```

```powershell
python run_ui.py --agent-port 2124 --ui-port 3100
python run_ui.py --frontend-dir C:\path\to\deep-agents-ui
```

Архив содержит Linux x86_64 `node_modules`, собранные для Node.js 20. Его нельзя
заменять архивом Windows `node_modules`. При изменении файлов frontend, patch,
`package.json` или `yarn.lock` архив и `SHA256SUMS` нужно пересоздать.

Сборка архива в WSL:

```powershell
wsl -d Ubuntu -- bash /mnt/c/path/to/deepagent/scripts/build_ui_archive.sh
```

Python-инициализация агента не живёт в `local_ui`. LangGraph config указывает на
`adapters/langgraph_agent_server.py:agent`; сам adapter вызывает core `build_agent(...)`.
В `local_ui` остаются только launcher/config/frontend-файлы.

Параметры KitAI-модели для UI задаются явно в словаре `KITAI_MODEL_CONFIG` файла
`adapters/langgraph_agent_server.py`. Env-переменные для ключей и параметров модели не
используются.

По умолчанию:

- UI: `http://127.0.0.1:3000`;
- Agent Server: `http://127.0.0.1:2024`;
- Assistant ID: `analytics-agent`.

Если страница белая, а в логе Next.js есть `Blocked cross-origin request ... from "127.0.0.1"`,
перезапустите `start.ps1` после обновления репозитория. В dev-режиме Next.js 16 блокирует
`/_next/*`, если UI открыт по `127.0.0.1`, а dev server слушает только `localhost`. Временный
обход: откройте `http://localhost:3000` или очистите `localStorage` ключ `deep-agent-config`,
если в Settings сохранён старый deployment URL.

Другие порты:

```powershell
powershell -ExecutionPolicy Bypass -File local_ui\start.ps1 -AgentPort 2124 -UiPort 3100
```

## Ошибки

- Ошибки запуска backend и frontend печатаются в stderr launcher-а; для backend также
  создаются отдельные stdout/stderr логи в `local_ui/.runtime/logs`.
- После исчерпания повторов временная ошибка провайдера преобразуется backend в
  пользовательское AI-сообщение. UI показывает краткое русскоязычное объяснение,
  тип исключения, HTTP-код при наличии и очищенный текст без API-ключей.
- Ошибки tools остаются в соответствующих карточках tool calls и доступны в истории
  LangGraph thread.

## Стриминг

В UI работают **два разных** вида стриминга:

1. **Стриминг графа LangGraph** — обновления шагов агента (tool calls, план, готовые
   сообщения). Его использует `deep-agents-ui`; без него интерфейс не покажет прогресс.
2. **Token-streaming модели** — посимвольная печать ответа LLM. Поддержка определяется
   моделью, которую собирает core adapter. Граф LangGraph, tool calls и промежуточные
   обновления UI работают независимо от token-streaming провайдера.

## Артефакты и ограничения

Чтобы файл появился в панели Files, agent должен записать текстовый файл в
`/artifacts/`. Большие `.pkl`, изображения и другие бинарные файлы остаются на
локальном диске, а UI показывает путь к ним в tool result.

Локальный patch обновляет frontend SDK, синхронизирует переключение threads через
`switchThread`, включает `fetchStateHistory`, `filterSubagentMessages`, связывает `task` с
`stream.subagents` по `tool_call.id` и строит approval UI по `stream.interrupts`.
Поэтому карточка subagent обновляется во время выполнения, показывает задачу,
lifecycle-статус, сообщения, вложенные tool calls, итоговый результат и approval для
`write_file`/`edit_file` внутри subagent.

В этом минимальном проходе большой архив
`deep-agents-ui-node20-linux-x86_64.tar.gz.part*` не пересобирался. Для offline transfer
после frontend-правок нужно отдельно пересобрать архив и обновить `SHA256SUMS`.
