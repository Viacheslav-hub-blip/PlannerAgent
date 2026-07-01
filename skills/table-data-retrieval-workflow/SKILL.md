---
name: table-data-retrieval-workflow
description: "Используй этот workflow-skill для ответов на пользовательские запросы, связанные с таблицами, выгрузкой данных, расчетами по выгрузкам, выбором периодов, выбором таблиц и постановкой задач data-retrieval-agent и coding-agent."
---

# Workflow выгрузки табличных данных

Файл описывает логику размышлений для запросов к таблицам.
Содержит: алгоритм определения периода, выбора таблиц, выбора столбцов, постановки задач data-retrieval-agent,
передачи результатов coding-agent и один полный пример плана с вызовами инструментов и агентов.

## Цель

Используй этот skill, когда пользователь просит найти, выгрузить, сравнить, посчитать или агрегировать данные из таблиц.
Основной результат supervisor-а: подтвержденный план выгрузок, отдельные задачи на каждую выгрузку и финальный синтез
только по фактически полученным данным.

Не придумывай названия таблиц, полей, фильтров, дат, количества строк и бизнес-смыслы. Все это должно быть подтверждено
skills, tool outputs или результатами агентов.

## Алгоритм

1. Разбери запрос пользователя.
   - Определи бизнес-вопрос: что именно нужно вернуть.
   - Выдели период, сущности, фильтры, группировки, метрики и ожидаемый формат ответа.
   - Если период важен, но не задан, задай короткий уточняющий вопрос.

2. Нормализуй период до точных дат.
   - Если пользователь задал относительный период относительно текущей даты (`вчера`, `сегодня`, `прошлый месяц`,
     `прошлая неделя`, `за последние N дней`), сначала определи текущую дату через tool `python`.
   - Если пользователь просит неделю по номеру (`неделя 47`, `47-я неделя`), сначала вычисли границы недели через
     tool `python`. Если пользователь не уточнил год, используй год из контекста запроса; если года нет, используй
     текущий год и явно укажи это допущение.
   - Если тип нумерации недели не задан, используй ISO-неделю: понедельник - воскресенье.
   - Для partitioned/event tables при известном периоде используй фильтр по `event_dt`, если skill таблицы не требует
     другой ключ периода.

3. Выбери таблицы.
   - Определи, какие table-skills нужны для ответа: например `/skills/hit-table/SKILL.md`,
     `/skills/cards-event-table/SKILL.md`, `/skills/uko-event-table/SKILL.md`.
   - Если краткой карточки таблицы недостаточно, загрузи `fields.md` или `joins.md`, на которые ссылается table-skill.
   - Если для ответа нужны несколько таблиц, каждая таблица выгружается отдельной задачей для `data-retrieval-agent`.
   - Если для ответа нужны несколько независимых периодов, каждая пара `таблица + период` выгружается отдельной задачей
     для `data-retrieval-agent`.

4. Выбери столбцы.
   - Запрашивай минимальный достаточный набор колонок: ключи связи, поля периода, поля фильтров, поля группировок,
     поля метрик и поля для проверки качества результата.
   - Не выбирай редкие поля без подтверждения в `fields.md`.
   - Для связей между таблицами заранее зафиксируй join keys и проверь их в `joins.md`, если связь не очевидна.

5. Поставь задачи на выгрузку.
   - Для каждой выгрузки передай `data-retrieval-agent` отдельную задачу с objective, таблицей, точным периодом,
     полями, фильтрами, expected evidence и stopping condition.
   - Требуй compact evidence: использованные skills, source table, filters, selected columns, row count, artifact path,
     ограничения и ошибки.
   - Если data-retrieval-agent вернул ошибку, измени аргументы или подход; не повторяй тот же вызов без новой причины.

6. Обработай выгрузки.
   - После получения всех нужных выгрузок передай `coding-agent` задачу на срезы, join, агрегации, проверки и подготовку
     итоговых таблиц.
   - Передавай coding-agent только фактические artifact paths, схему результата, нужные метрики и правила агрегации.
   - Не заставляй coding-agent повторно выгружать данные: он должен работать с уже полученными артефактами.

7. Сделай финальный ответ.
   - Покажи результат и коротко опиши, какие таблицы, периоды, фильтры и ограничения использованы.
   - Если часть данных не получена, явно отдели подтвержденные выводы от ограничений.
   - Не скрывай нулевые результаты: если выгрузка за корректный период вернула 0 строк, так и напиши.

## Шаблон задачи для data-retrieval-agent

```text
delegate data-retrieval-agent(
  objective: "Выгрузить <что именно нужно получить>",
  inputs:
    user_request: "<исходный запрос пользователя или релевантная часть>",
    table: "<подтвержденная таблица>",
    period:
      field: "event_dt"
      from: "YYYYMMDD"
      to: "YYYYMMDD"
    selected_columns:
      - "<column_1>"
      - "<column_2>"
    filters:
      - "<filter_1>"
      - "<filter_2>"
    relevant_skills:
      - "/skills/<table-skill>/SKILL.md"
      - "/skills/<table-skill>/fields.md, если нужен"
      - "/skills/<table-skill>/joins.md, если нужен"
  expected_evidence:
    - source table
    - selected columns
    - period filter
    - material filters
    - row count
    - artifact path
    - limitations/errors
  stopping_condition: "Остановиться после успешной полной выгрузки или после одной осмысленной коррекции ошибки."
)
```

## Шаблон задачи для coding-agent

```text
delegate coding-agent(
  objective: "Посчитать итоговые срезы и агрегации по готовым выгрузкам",
  inputs:
    artifacts:
      - "<artifact_path_1>"
      - "<artifact_path_2>"
    operations:
      - "проверить типы и пропуски в ключевых колонках"
      - "выполнить join по <join_key>, если нужен"
      - "посчитать <метрики> по <группировки>"
    output:
      format: "compact markdown table plus saved artifact if result is large"
  validation:
    - "сверить row counts входных артефактов"
    - "показать количество строк после фильтров/join"
    - "не использовать данные вне переданных artifacts"
  stopping_condition: "Остановиться после получения итоговой таблицы и compact evidence расчетов."
)
```

## Полный пример

Запрос пользователя:

```text
Покажи за прошлый месяц и за 47-ю неделю 2025 года количество сработок по правилу
"DENY оплата обучения", среднюю сумму в рублях и сколько из этих сработок найдено в cards.
```

План supervisor-а:

1. Определить точные периоды.
2. Загрузить skills по `hits` и `cards`, при необходимости `joins.md`.
3. Разделить выгрузки на 4 задачи:
   - `hits` за прошлый месяц;
   - `hits` за ISO-неделю 47 2025 года;
   - `cards` за прошлый месяц;
   - `cards` за ISO-неделю 47 2025 года.
4. После выгрузок передать artifacts coding-agent для фильтрации, связи `hits` с `cards`, подсчета количества и средней суммы.

Вызов python для дат:

```text
python:
  purpose: "Определить текущую дату, границы прошлого месяца и ISO-недели 47 2025 года"
  code: |
    from datetime import date, timedelta

    today = date.today()
    first_day_current_month = today.replace(day=1)
    last_day_previous_month = first_day_current_month - timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)

    week_start = date.fromisocalendar(2025, 47, 1)
    week_end = date.fromisocalendar(2025, 47, 7)

    print({
        "today": today.isoformat(),
        "previous_month_from": first_day_previous_month.strftime("%Y%m%d"),
        "previous_month_to": last_day_previous_month.strftime("%Y%m%d"),
        "iso_week_47_2025_from": week_start.strftime("%Y%m%d"),
        "iso_week_47_2025_to": week_end.strftime("%Y%m%d"),
    })
```

Пример результата python при текущей дате `2026-07-01`:

```text
previous_month_from: 20260601
previous_month_to: 20260630
iso_week_47_2025_from: 20251117
iso_week_47_2025_to: 20251123
```

Задача 1 для data-retrieval-agent:

```text
delegate data-retrieval-agent(
  objective: "Выгрузить сработки hits по правилу DENY оплата обучения за прошлый месяц",
  inputs:
    table: "hits"
    period:
      field: "event_dt"
      from: "20260601"
      to: "20260630"
    selected_columns:
      - "event_id"
      - "event_dt"
      - "epk_id"
      - "main_rule"
      - "transaction_amount_in_rub"
    filters:
      - "main_rule CONTAINS 'DENY оплата обучения'"
    relevant_skills:
      - "/skills/hit-table/SKILL.md"
  expected_evidence:
    - "source table, period filter, selected columns, row count, artifact path, limitations"
  stopping_condition: "Остановиться после полной выгрузки или после одной осмысленной коррекции ошибки."
)
```

Задача 2 для data-retrieval-agent:

```text
delegate data-retrieval-agent(
  objective: "Выгрузить сработки hits по правилу DENY оплата обучения за ISO-неделю 47 2025 года",
  inputs:
    table: "hits"
    period:
      field: "event_dt"
      from: "20251117"
      to: "20251123"
    selected_columns:
      - "event_id"
      - "event_dt"
      - "epk_id"
      - "main_rule"
      - "transaction_amount_in_rub"
    filters:
      - "main_rule CONTAINS 'DENY оплата обучения'"
    relevant_skills:
      - "/skills/hit-table/SKILL.md"
  expected_evidence:
    - "source table, period filter, selected columns, row count, artifact path, limitations"
  stopping_condition: "Остановиться после полной выгрузки или после одной осмысленной коррекции ошибки."
)
```

Задача 3 для data-retrieval-agent:

```text
delegate data-retrieval-agent(
  objective: "Выгрузить события cards за прошлый месяц для связи со сработками hits",
  inputs:
    table: "cards"
    period:
      field: "event_dt"
      from: "20260601"
      to: "20260630"
    selected_columns:
      - "event_id"
      - "event_dt"
      - "epk_id"
    filters:
      - "event_id IS NOT NULL"
    relevant_skills:
      - "/skills/cards-event-table/SKILL.md"
      - "/skills/hit-table/joins.md"
  expected_evidence:
    - "source table, period filter, selected columns, row count, artifact path, limitations"
  stopping_condition: "Остановиться после полной выгрузки или после одной осмысленной коррекции ошибки."
)
```

Задача 4 для data-retrieval-agent:

```text
delegate data-retrieval-agent(
  objective: "Выгрузить события cards за ISO-неделю 47 2025 года для связи со сработками hits",
  inputs:
    table: "cards"
    period:
      field: "event_dt"
      from: "20251117"
      to: "20251123"
    selected_columns:
      - "event_id"
      - "event_dt"
      - "epk_id"
    filters:
      - "event_id IS NOT NULL"
    relevant_skills:
      - "/skills/cards-event-table/SKILL.md"
      - "/skills/hit-table/joins.md"
  expected_evidence:
    - "source table, period filter, selected columns, row count, artifact path, limitations"
  stopping_condition: "Остановиться после полной выгрузки или после одной осмысленной коррекции ошибки."
)
```

Задача для coding-agent после получения всех artifacts:

```text
delegate coding-agent(
  objective: "Сравнить метрики hits за два периода и посчитать наличие связанных событий cards",
  inputs:
    artifacts:
      - "<hits_previous_month_artifact>"
      - "<hits_week_47_artifact>"
      - "<cards_previous_month_artifact>"
      - "<cards_week_47_artifact>"
    operations:
      - "для каждого периода посчитать count hits"
      - "для каждого периода посчитать mean(transaction_amount_in_rub)"
      - "для каждого периода выполнить left join hits к cards по event_id"
      - "посчитать количество hits, для которых найден matching cards.event_id"
    output:
      columns:
        - "period"
        - "hits_count"
        - "avg_transaction_amount_in_rub"
        - "matched_cards_count"
        - "matched_cards_share"
  validation:
    - "показать row count каждого входного artifact"
    - "показать row count после join"
    - "не использовать данные вне переданных artifacts"
  stopping_condition: "Остановиться после compact evidence и итоговой таблицы."
)
```

Финальный ответ supervisor-а должен ссылаться только на compact evidence от data-retrieval-agent и coding-agent:
периоды, таблицы, фильтры, количество строк, artifact paths, итоговые метрики и ограничения.
