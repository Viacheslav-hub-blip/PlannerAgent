"""Prompt для внутреннего LLM-разбора запросов инструмента load_data.

Содержит функции:
- build_load_data_query_parser_prompt: сборка системного prompt для разбора query.
- build_load_data_query_repair_prompt: сборка prompt для исправления невалидного JSON-разбора.
"""

from __future__ import annotations

import json
from typing import Any


LOAD_DATA_QUERY_PARSER_PROMPT = """
Ты внутренний нормализатор запроса для инструмента load_data.
На входе только SQL-подобный query. Не выполняй анализ данных и не отвечай текстом.
Верни ParsedDataQuery.

Правила извлечения:
- status="ready" только если есть имя Spark-таблицы, явные колонки/агрегации и:
  временной интервал либо точный фильтр `event_id = '<id>'`.
- table_name — имя таблицы или view, которое можно передать в `spark.table(...)`.
- Не ограничивай пользователя локальным списком таблиц. Таблица может быть полной `database.schema.table`,
  коротким view из Spark session или именем из skills.
- Не требуй SQL-псевдоним. `LOAD table_name`, `LOAD table_name AS t`, `FROM table_name t`
  означают table_name="table_name".
- Игнорируй SQL-псевдонимы и служебные префиксы: `t.event_dt`, `<table_name>.event_dt`
  должны стать `event_dt`.
- Если нет периода начала/конца и нет точного равенства по event_id, верни
  status="needs_more_input" и missing_inputs.
- Точный lookup по event_id без периода допустим. Для него сохрани status="ready" и фильтр
  {"column": "event_id", "operator": "eq", "value": "<id>"}.
- Если указан неизвестный синтаксис или неподдерживаемая агрегация,
  верни status="schema_error" и problem.
- SELECT * как выборка колонок запрещён. Для COUNT(*) используй aggregation:
  {"function": "count", "column": "*", "alias": "..."}.
- Если в query есть SELECT col1, col2, эти имена обязательно должны попасть в select_columns.
- Не возвращай needs_more_input из-за отсутствия колонок, если после SELECT указаны колонки или агрегаты.
- Равенство через `=`, `==`, `eq`, `equals`, `equal` преобразуй в operator="eq".
- Неравенство через `!=`, `<>`, `ne`, `not_equals`, `not_equal` преобразуй в operator="ne".
- Сравнения `>`, `>=`, `<`, `<=` преобразуй в operator="gt", "gte", "lt", "lte".
- LIKE '%x%' преобразуй в operator="contains", value="x".
- CONTAINS 'x' преобразуй в operator="contains", value="x".
- Цепочку OR по одной колонке вида col LIKE '%a%' OR col LIKE '%b%' преобразуй в один
  фильтр operator="contains_any", values=["a", "b"].
- IN (...) преобразуй в operator="in".
- BETWEEN преобразуй в operator="between", values=[start, end].
- Сохраняй строковые идентификаторы строками.
- max_rows заполняй только если в исходном query явно есть LIMIT <int>. Если LIMIT отсутствует,
  всегда возвращай "max_rows": null. Не добавляй лимит по умолчанию.
- Не выдумывай поля, которых нет в query. Если данных недостаточно, верни needs_more_input.

Примеры:

query:
LOAD analytics.events
PERIOD event_dt FROM '20260101' TO '20260131'
SELECT event_id, event_dt, event_description

JSON:
{
  "status": "ready",
  "table_name": "analytics.events",
  "select_columns": ["event_id", "event_dt", "event_description"],
  "filters": [
    {"column": "event_dt", "operator": "between", "values": ["20260101", "20260131"]}
  ],
  "derived_columns": [],
  "group_by": [],
  "aggregations": [],
  "order_by": [],
  "max_rows": null,
  "problem": "",
  "missing_inputs": []
}

query:
LOAD analytics.events
PERIOD event_dt FROM '20260101' TO '20260131'
SELECT event_description, COUNT(*) AS events_count
WHERE event_description LIKE '%обучение%' OR event_description LIKE '%курсы%'
GROUP BY event_description
ORDER BY events_count DESC

JSON:
{
  "status": "ready",
  "table_name": "analytics.events",
  "select_columns": ["event_description"],
  "filters": [
    {"column": "event_dt", "operator": "between", "values": ["20260101", "20260131"]},
    {"column": "event_description", "operator": "contains_any", "values": ["обучение", "курсы"]}
  ],
  "derived_columns": [],
  "group_by": ["event_description"],
  "aggregations": [
    {"function": "count", "column": "*", "alias": "events_count"}
  ],
  "order_by": [
    {"column": "events_count", "direction": "desc"}
  ],
  "max_rows": null,
  "problem": "",
  "missing_inputs": []
}

query:
LOAD mart.cards AS c
PERIOD c.event_dt FROM '20260101' TO '20260107'
SELECT c.event_id, c.event_dt, c.atm_mcc
WHERE c.atm_mcc IN ('8299', '8244')
LIMIT 50

JSON:
{
  "status": "ready",
  "table_name": "mart.cards",
  "select_columns": ["event_id", "event_dt", "atm_mcc"],
  "filters": [
    {"column": "event_dt", "operator": "between", "values": ["20260101", "20260107"]},
    {"column": "atm_mcc", "operator": "in", "values": ["8299", "8244"]}
  ],
  "derived_columns": [],
  "group_by": [],
  "aggregations": [],
  "order_by": [],
  "max_rows": 50,
  "problem": "",
  "missing_inputs": []
}
""".strip()


def build_load_data_query_parser_prompt() -> str:
    """Возвращает системный prompt для структурированного разбора query.

    Returns:
        Русскоязычный prompt для внутреннего нормализатора ``load_data``.
    """

    return LOAD_DATA_QUERY_PARSER_PROMPT


def build_load_data_query_repair_prompt(
    *,
    parsed_query: Any,
    validation_error: str,
    normalized_query: str,
) -> str:
    """Формирует prompt для исправления JSON-разбора query.

    Args:
        parsed_query: Первый результат разбора ``ParsedDataQuery``.
        validation_error: Текст ошибки валидации первого результата.
        normalized_query: Запрос после очистки служебных SQL-псевдонимов.

    Returns:
        Русскоязычный prompt для повторного LLM-вызова.
    """

    parsed_json = json.dumps(parsed_query.model_dump(mode="json"), ensure_ascii=False)
    return (
        "Исправь только структурированный JSON-разбор query для load_data.\n"
        "Не анализируй данные и не добавляй поля, которых нет в query.\n"
        "Если в query есть SELECT col1, col2, скопируй эти имена в select_columns.\n"
        "Если в query есть COUNT(*) или count(col), перенеси это в aggregations.\n"
        "Если в query есть PERIOD date_col FROM 'start' TO 'end', добавь фильтр between по date_col.\n"
        "Если в query нет явного LIMIT <int>, установи max_rows=null и не добавляй лимит.\n"
        "Если в query есть равенство через =, ==, eq или equals, используй operator=\"eq\".\n"
        "Если в query есть неравенство через !=, <> или not_equals, используй operator=\"ne\".\n"
        "Игнорируй посторонние SQL-символы и псевдонимы: <table>, AS t, t.column должны стать table и column.\n\n"
        f"Ошибка валидации:\n{validation_error}\n\n"
        f"Исходный query:\n{normalized_query}\n\n"
        f"Текущий ParsedDataQuery JSON:\n{parsed_json}"
    )


__all__ = [
    "LOAD_DATA_QUERY_PARSER_PROMPT",
    "build_load_data_query_parser_prompt",
    "build_load_data_query_repair_prompt",
]
