# Локальный Deep Agents UI

Папка подключает текущий аналитический DeepAgent к официальному
[`langchain-ai/deep-agents-ui`](https://github.com/langchain-ai/deep-agents-ui)
через штатный LangGraph Agent Server.

## Что видно в UI

- план из встроенного `write_todos`;
- аргументы, статус и результат вызовов инструментов;
- запуск `task` и итоговый ответ subagent;
- текстовые артефакты из `/artifacts/`;
- история threads и запросы на approval для `write_file`/`edit_file`.

Скрытая цепочка рассуждений модели не публикуется. Вместо неё agent prompt просит
давать короткие проверяемые резюме намерений и результатов обычными сообщениями.

## Установка

Требования: Python 3.11+, существующая `.venv`, Git и Node.js 20+.

```powershell
powershell -ExecutionPolicy Bypass -File local_ui\install.ps1
```

Скрипт:

1. установит optional dependency `ui`;
2. клонирует UI в `local_ui/.runtime/deep-agents-ui`;
3. закрепит commit `f6a4f34565b42688be06498031fc9351c152614e`;
4. применит минимальный patch автоподключения к локальному backend;
5. создаст `local_ui/.env`, если его ещё нет.

Заполните `local_ui/.env`. Используются только переменные окружения; ключи из
`model.py` этот entrypoint не импортирует.

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
DEEP_AGENT_MODEL=z-ai/glm-5
```

## Запуск

```powershell
powershell -ExecutionPolicy Bypass -File local_ui\start.ps1
```

По умолчанию:

- UI: `http://127.0.0.1:3000`;
- Agent Server: `http://127.0.0.1:2024`;
- Assistant ID: `analytics-agent`.

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

## Артефакты и ограничения

Чтобы файл появился в панели Files, agent должен записать текстовый файл в
`/artifacts/`. Большие `.pkl`, изображения и другие бинарные файлы остаются на
локальном диске, а UI показывает путь к ним в tool result.

Upstream UI показывает `task` с input/output, но не раскрывает вложенные tool calls
внутри subagent. Это текущее ограничение `deep-agents-ui`; верхнеуровневые вызовы
инструментов отображаются полностью.

