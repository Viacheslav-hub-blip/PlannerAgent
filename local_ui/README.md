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

Скрытая цепочка рассуждений модели не публикуется. Вместо неё agent prompt просит
давать короткие проверяемые резюме намерений и результатов обычными сообщениями.

## Запуск одной командой

Требования: Python 3.11+, Git и Node.js 20+. Виртуальное окружение `.venv` желательно,
но скрипт работает и с текущим `python`.

```powershell
python run_ui.py
```

Первый запуск сам:

1. установит optional dependency `ui` и остальные extras;
2. клонирует UI в `local_ui/.runtime/deep-agents-ui`;
3. закрепит commit `f6a4f34565b42688be06498031fc9351c152614e`;
4. применит patch автоподключения к локальному backend;
5. создаст `local_ui/.env`, если его ещё нет;
6. поднимет Agent Server и UI.

Повторные запуски быстрее: зависимости переустанавливаются только при необходимости.

```powershell
python run_ui.py --skip-install
python run_ui.py --install-only
python run_ui.py --agent-port 2124 --ui-port 3100
```

Заполните `local_ui/.env`. Используются только переменные окружения; ключи из
`model.py` этот entrypoint не импортирует.

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
DEEP_AGENT_MODEL=z-ai/glm-5
```

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

## Пример из тестовой корзины

Получить актуальный текст кейса 1:

```powershell
.\.venv\Scripts\python.exe local_ui\example_query.py --case-id 1
```

После запуска UI отправьте напечатанный запрос:

> Сколько сработок правила «DENY оплата обучения после смены устройства» было
> с 24 января по 6 февраля 2026 года включительно?

В интерфейсе появятся план, вызов `load_data`, его аргументы/результат и итоговый
ответ. Для этого кейса тестовая корзина ожидает число `7`.

## Стриминг

В UI работают **два разных** вида стриминга:

1. **Стриминг графа LangGraph** — обновления шагов агента (tool calls, план, готовые
   сообщения). Его использует `deep-agents-ui`; без него интерфейс не покажет прогресс.
2. **Token-streaming модели** — посимвольная печать ответа LLM. Если провайдер его не
   поддерживает, задайте в `local_ui/.env`:

```env
DEEP_AGENT_DISABLE_STREAMING=true
```

Тогда LangChain вызывает модель через обычный `invoke`, а не `astream`. Агент и UI
продолжают работать: текст ответа появится целиком после завершения шага модели, плюс
по-прежнему стримятся вызовы инструментов и промежуточные обновления графа.

## Артефакты и ограничения

Чтобы файл появился в панели Files, agent должен записать текстовый файл в
`/artifacts/`. Большие `.pkl`, изображения и другие бинарные файлы остаются на
локальном диске, а UI показывает путь к ним в tool result.

Локальный patch обновляет frontend SDK и связывает `task` с
`stream.getSubagentsByMessage(message.id)`. Поэтому карточка subagent обновляется
во время выполнения и показывает задачу, lifecycle-статус, сообщения, вложенные
tool calls и итоговый результат.
