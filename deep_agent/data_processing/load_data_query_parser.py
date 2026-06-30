"""LLM-разбор SQL-подобных запросов для инструмента load_data.

Содержит функции:
- _extract_query_args_with_llm: основной разбор запроса;
- _invoke_query_parser_json_fallback: JSON fallback модели;
- _repair_parsed_query_with_llm: исправление невалидного разбора;
- _format_parsed_query_debug: диагностическое представление;
- _message_text: извлечение текста сообщения;
- _extract_json_object: извлечение JSON;
- _normalize_query_text_for_parser: подготовка исходного текста;
- _parsed_query_to_read_args: преобразование схемы в аргументы backend;
- _validate_parsed_query: проверка обязательных полей;
- _normalize_table_name: нормализация имени таблицы;
- _normalize_column_name: нормализация колонки;
- _normalize_filter_item: нормализация фильтра;
- _normalize_derived_item: нормализация вычисляемой колонки;
- _normalize_aggregation_item: нормализация агрегата;
- _normalize_order_item: нормализация сортировки;
- _has_required_period: проверка периода;
- _has_exact_event_id_filter: проверка точного event_id;
- _dump_model: преобразование модели в словарь.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deep_agent.data_processing.load_data_query_values import _get_field
from deep_agent.data_processing.load_data_query_models import (
    ParsedDataQuery,
    normalize_filter_operator,
)
from deep_agent.prompts.load_data_query_parser_prompt import (
    build_load_data_query_parser_prompt,
    build_load_data_query_repair_prompt,
)
def _extract_query_args_with_llm(*, query: str, query_parser_model: Any | None) -> dict[str, Any]:
    """Извлекает аргументы выборки из SQL-подобного запроса с помощью LLM.

    Args:
        query: SQL-подобный запрос, который написал data-retrieval-agent.
        query_parser_model: Chat-модель LangChain для JSON-разбора ``query``.

    Returns:
        Словарь аргументов, совместимый с внутренней функцией ``_read_table``.

    Raises:
        ValueError: Модель разбора не передана или LLM вернул неполную структуру запроса.
    """

    if query_parser_model is None:
        raise ValueError(
            "для load_data не передана query_parser_model. "
            "Собери data tool с query_parser_model=model."
        )

    messages = [
        ("system", build_load_data_query_parser_prompt()),
        ("human", _normalize_query_text_for_parser(query)),
    ]
    parsed = _invoke_query_parser_json_fallback(query_parser_model=query_parser_model, messages=messages)
    try:
        return _parsed_query_to_read_args(parsed)
    except ValueError as first_error:
        repaired = _repair_parsed_query_with_llm(
            query_parser_model=query_parser_model,
            query=query,
            parsed=parsed,
            validation_error=str(first_error),
        )
        if repaired is not None:
            try:
                return _parsed_query_to_read_args(repaired)
            except ValueError as repaired_error:
                raise ValueError(
                    f"{repaired_error}\nLLM parser output: {_format_parsed_query_debug(repaired)}"
                ) from repaired_error
        raise ValueError(f"{first_error}\nLLM parser output: {_format_parsed_query_debug(parsed)}") from first_error




def _invoke_query_parser_json_fallback(*, query_parser_model: Any, messages: list[tuple[str, str]]) -> ParsedDataQuery:
    """Вызывает модель без structured-output и разбирает JSON из текстового ответа.

    Args:
        query_parser_model: Chat-модель LangChain.
        messages: Сообщения system/human для внутреннего нормализатора.

    Returns:
        Pydantic-модель ``ParsedDataQuery``.

    Raises:
        ValueError: Модель не вернула JSON, совместимый с ``ParsedDataQuery``.
    """

    fallback_messages = [
        messages[0],
        (
            "human",
            f"{messages[1][1]}\n\nВерни только JSON-объект без Markdown и пояснений.",
        ),
    ]
    raw = query_parser_model.invoke(fallback_messages)
    try:
        return ParsedDataQuery.model_validate(_extract_json_object(_message_text(raw)))
    except Exception as exc:
        raise ValueError(f"LLM parser не вернул валидный ParsedDataQuery JSON: {exc}") from exc


def _repair_parsed_query_with_llm(
    *,
    query_parser_model: Any,
    query: str,
    parsed: ParsedDataQuery,
    validation_error: str,
) -> ParsedDataQuery | None:
    """Повторно просит LLM исправить результат разбора, если первый JSON не прошёл валидацию.

    Args:
        query_parser_model: Chat-модель LangChain для внутреннего разбора запроса.
        query: Исходный SQL-подобный запрос, который передал агент.
        parsed: Первый структурированный результат разбора.
        validation_error: Ошибка обязательной валидации первого результата.

    Returns:
        Исправленная модель ``ParsedDataQuery`` или ``None``, если repair-вызов не дал валидный JSON.
    """

    repair_prompt = build_load_data_query_repair_prompt(
        parsed_query=parsed,
        validation_error=validation_error,
        normalized_query=_normalize_query_text_for_parser(query),
    )
    try:
        return _invoke_query_parser_json_fallback(
            query_parser_model=query_parser_model,
            messages=[("system", build_load_data_query_parser_prompt()), ("human", repair_prompt)],
        )
    except ValueError:
        return None


def _format_parsed_query_debug(parsed: ParsedDataQuery) -> str:
    """Формирует короткий JSON-дамп результата LLM-разбора для диагностики ошибок инструмента.

    Args:
        parsed: Структурированный результат LLM-разбора.

    Returns:
        JSON-строка с ключевыми полями ``ParsedDataQuery``.
    """

    return json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False)


def _message_text(message: Any) -> str:
    """Извлекает текст из ответа chat-модели.

    Args:
        message: Ответ LangChain chat model или строка.

    Returns:
        Текстовое содержимое ответа.
    """

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Извлекает первый JSON-объект из текста модели.

    Args:
        text: Текстовый ответ LLM.

    Returns:
        Распарсенный JSON-объект.

    Raises:
        ValueError: В тексте нет JSON-объекта.
    """

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("в ответе модели нет JSON-объекта.")
    return json.loads(cleaned[start : end + 1])


def _normalize_query_text_for_parser(query: str) -> str:
    """Убирает из SQL-подобного запроса шум, который не должен влиять на LLM-разбор.

    Args:
        query: Исходный SQL-подобный запрос.

    Returns:
        Запрос без угловых скобок вокруг таблиц и без SQL-alias после ``LOAD``/``FROM``.
    """

    text = query.strip()
    text = re.sub(r"<([A-Za-z_][\w]*)>", r"\1", text)
    text = re.sub(r"(?im)^(\s*LOAD\s+)([A-Za-z_][\w]*)(?:\s+AS)?\s+[A-Za-z_][\w]*(\s*)$", r"\1\2\3", text)
    text = re.sub(
        r"(?is)\bFROM\s+([A-Za-z_][\w]*)(?:\s+AS)?\s+[A-Za-z_][\w]*\b",
        r"FROM \1",
        text,
    )
    return text


def _parsed_query_to_read_args(parsed: ParsedDataQuery) -> dict[str, Any]:
    """Преобразует результат LLM-разбора в аргументы внутренней выборки.

    Args:
        parsed: Структурированный результат LLM-разбора запроса.

    Returns:
        Словарь аргументов для ``_read_table``.

    Raises:
        ValueError: LLM сообщил проблему или вернул неполный запрос.
    """

    exact_event_id_lookup = _has_exact_event_id_filter(parsed.filters)
    if parsed.status != "ready" and not exact_event_id_lookup:
        details = parsed.problem or ", ".join(parsed.missing_inputs) or "query нельзя выполнить."
        raise ValueError(f"{parsed.status}: {details}")
    _validate_parsed_query(parsed)
    table_name = _normalize_table_name(parsed.table_name)
    filters = [_normalize_filter_item(_dump_model(item)) for item in parsed.filters]
    derived_columns = [_normalize_derived_item(_dump_model(item)) for item in parsed.derived_columns]
    aggregations = [_normalize_aggregation_item(_dump_model(item)) for item in parsed.aggregations]
    order_by = [_normalize_order_item(_dump_model(item)) for item in parsed.order_by]
    return {
        "table_name": table_name,
        "select_columns": [_normalize_column_name(column) for column in parsed.select_columns if str(column).strip()],
        "filters": filters,
        "derived_columns": derived_columns,
        "group_by": [_normalize_column_name(column) for column in parsed.group_by if str(column).strip()],
        "aggregations": aggregations,
        "order_by": order_by,
        "max_rows": parsed.max_rows,
    }


def _validate_parsed_query(parsed: ParsedDataQuery) -> None:
    """Проверяет обязательные части запроса после LLM-разбора.

    Args:
        parsed: Структурированный результат LLM-разбора запроса.

    Returns:
        ``None``, если запрос можно выполнять.

    Raises:
        ValueError: В запросе нет обязательных колонок, периода или таблицы.
    """

    table_name = _normalize_table_name(parsed.table_name)
    if not table_name:
        raise ValueError("needs_more_input: в query не указано имя Spark-таблицы.")
    select_columns = [str(column).strip() for column in parsed.select_columns if str(column).strip()]
    if {column.lower() for column in select_columns} & {"*", "all"}:
        raise ValueError("schema_error: SELECT * и SELECT all запрещены для обычной выборки.")
    if not select_columns and not parsed.aggregations:
        raise ValueError("needs_more_input: в query нет явных колонок результата или агрегаций.")
    if not _has_required_period(parsed.filters) and not _has_exact_event_id_filter(parsed.filters):
        raise ValueError(
            "needs_more_input: в query нет временного интервала с двумя границами "
            "или точного фильтра event_id = <id>."
        )


def _normalize_table_name(value: Any) -> str:
    """Очищает имя таблицы от SQL-alias и служебных символов.

    Args:
        value: Значение ``table_name``, которое вернул LLM.

    Returns:
        Имя Spark-таблицы или пустую строку.
    """

    text = str(value or "").strip().strip("`\"'").strip()
    text = re.sub(r"[<>]", "", text)
    text = re.sub(r"(?i)^\s*(LOAD|FROM)\s+", "", text).strip()
    text = re.split(r"(?i)\s+AS\s+|\s+", text, maxsplit=1)[0]
    return text.strip()


def _normalize_column_name(value: Any) -> str:
    """Очищает имя колонки от SQL-alias, кавычек и угловых скобок.

    Args:
        value: Имя колонки, которое вернул LLM.

    Returns:
        Имя колонки без префикса таблицы или SQL-alias.
    """

    text = str(value or "").strip().strip("`\"'").strip()
    text = re.sub(r"[<>]", "", text)
    if "." in text:
        text = text.split(".")[-1]
    return text.strip()


def _normalize_filter_item(item: dict[str, Any]) -> dict[str, Any]:
    """Очищает колонку фильтра от SQL-префиксов.

    Args:
        item: Фильтр, который вернул LLM.

    Returns:
        Фильтр с нормализованным именем колонки.
    """

    result = dict(item)
    result["column"] = _normalize_column_name(result.get("column"))
    result["operator"] = normalize_filter_operator(result.get("operator"))
    return result


def _normalize_derived_item(item: dict[str, Any]) -> dict[str, Any]:
    """Очищает вычисляемую колонку от SQL-префиксов.

    Args:
        item: Описание вычисляемой колонки.

    Returns:
        Описание с нормализованными именами колонок.
    """

    result = dict(item)
    result["name"] = _normalize_column_name(result.get("name"))
    result["source_column"] = _normalize_column_name(result.get("source_column"))
    return result


def _normalize_aggregation_item(item: dict[str, Any]) -> dict[str, Any]:
    """Очищает агрегат от SQL-префиксов.

    Args:
        item: Описание агрегата.

    Returns:
        Описание агрегата с нормализованной колонкой.
    """

    result = dict(item)
    column = str(result.get("column") or "").strip()
    result["column"] = "*" if column == "*" else _normalize_column_name(column)
    return result


def _normalize_order_item(item: dict[str, Any]) -> dict[str, Any]:
    """Очищает сортировку от SQL-префиксов.

    Args:
        item: Описание сортировки.

    Returns:
        Описание сортировки с нормализованной колонкой.
    """

    result = dict(item)
    result["column"] = _normalize_column_name(result.get("column"))
    return result


def _has_required_period(filters: list[Any]) -> bool:
    """Проверяет наличие фильтра временного интервала.

    Args:
        filters: Фильтры, которые вернул LLM-разбор.

    Returns:
        ``True``, если найден хотя бы один ``between`` с двумя границами.
    """

    for item in filters:
        operator = normalize_filter_operator(_get_field(item, "operator"))
        values = _get_field(item, "values") or []
        value = _get_field(item, "value")
        if operator == "between" and len(values) == 2:
            return True
    return False


def _has_exact_event_id_filter(filters: list[Any]) -> bool:
    """Проверяет наличие точного непустого фильтра по ``event_id``.

    Args:
        filters: Фильтры, которые вернул LLM-разбор.

    Returns:
        ``True`` только для ``event_id`` с оператором ``eq`` и непустым значением.
    """

    for item in filters:
        column = _normalize_column_name(_get_field(item, "column"))
        operator = normalize_filter_operator(_get_field(item, "operator"))
        value = _get_field(item, "value")
        if column == "event_id" and operator == "eq" and str(value or "").strip():
            return True
    return False


def _dump_model(value: Any) -> dict[str, Any]:
    """Преобразует pydantic-модель или dict в обычный словарь.

    Args:
        value: Pydantic-модель или словарь.

    Returns:
        Словарь с полями модели.
    """

    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)

