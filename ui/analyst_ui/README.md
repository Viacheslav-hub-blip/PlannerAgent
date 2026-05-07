# Research Agent React UI

React/Vite интерфейс для live-представления выполнения агента.

## Что есть в версии 0.13

- В графе теперь создаётся ровно один user-facing узел на одну задачу.
- Больше нет отдельных узлов:
  - `Постановка задачи 4`
  - `Постановка задачи finished`
  - `Результат задачи 4`
  - `Результат задачи finished`
- Узел задачи работает как живое состояние:
  - сначала показывает постановку задачи;
  - после появления результата показывает результат задачи;
  - статус узла обновляется до completed/succeeded только по явному `task_completed` или `validation_completed`.
- Исправлен парсинг `task_finished`: он больше не создаёт псевдо-задачу `finished`.
- В Inspector выбранной задачи отдельно видны:
  - постановка задачи;
  - результат задачи;
  - все raw lineage events внутри задачи.
- Branch открывается только по маленькой кнопке на узле, не по клику на сам узел.
- Сохранены:
  - performance-lite стиль;
  - компактное окно текущего плана;
  - zoom внутри canvas;
  - кликабельные raw events;
  - Markdown-отчёт.

## Dev

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main_ui_agent_server:create_app_with_agent --factory --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd .\ui\analyst_ui
npm install
npm run dev
```

Открыть:

```text
http://127.0.0.1:5173
```
