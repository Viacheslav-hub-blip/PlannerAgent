"""Разбор и проверка структурированных значений табличного запроса.

Содержит функции:
- _parse_columns: разбор колонок;
- _split_items: разбор списка инструкций;
- _parse_filter_item: разбор фильтра;
- _parse_filter_values: разбор значений фильтра;
- _parse_derived_item: разбор вычисляемой колонки;
- _parse_aggregation_item: разбор агрегата;
- _parse_order_item: разбор сортировки;
- _parse_scalar: преобразование скалярного значения;
- _normalize_filter_scalar: нормализация значения фильтра;
- _validate_columns: проверка колонок;
- _format_empty_select_error: ошибка пустого SELECT;
- _format_missing_columns: ошибка отсутствующих колонок;
- _get_field: чтение поля объекта.
"""

from __future__ import annotations

import re
from typing import Any

from deep_agent.data.query_schema import normalize_filter_operator

_FILTER_OPERATORS = {
    "eq", "ne", "gt", "gte", "lt", "lte", "contains", "contains_any",
    "in", "between", "is_null", "not_null",
}
_DERIVED_OPERATIONS = {"year", "month", "year_month", "date", "lower", "upper", "length", "abs"}
_AGGREGATION_FUNCTIONS = {"count", "count_distinct", "min", "max", "sum", "mean"}
def _parse_columns(value: Any) -> list[str]:
    """Разбирает строку колонок через запятую.

    Args:
        value: Список колонок или строка вида ``col1, col2``.

    Returns:
        Список колонок без пустых значений.
    """

    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _split_items(value: Any) -> list[Any]:
    """Разбирает строку инструкций через ``;`` или перенос строки.

    Args:
        value: Список инструкций или строка с несколькими инструкциями.

    Returns:
        Список непустых инструкций.
    """

    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item]
    normalized = str(value).replace("\n", ";")
    return [item.strip() for item in normalized.split(";") if item.strip()]


def _parse_filter_item(item: Any) -> tuple[str, str, str]:
    """Разбирает один фильтр.

    Args:
        item: Фильтр в структурированном формате или строка ``column operator value``.

    Returns:
        Кортеж ``(column, operator, value)``.
    """

    if not isinstance(item, str):
        column = str(_get_field(item, "column") or "").strip()
        operator = normalize_filter_operator(_get_field(item, "operator"))
        values = _get_field(item, "values") or []
        value = _get_field(item, "value")
        if operator not in _FILTER_OPERATORS:
            raise ValueError(f"Неподдерживаемый оператор фильтра: {operator}")
        if operator in {"in", "contains_any"}:
            raw_values = values if values else ([] if value is None else [value])
            raw_value = ",".join(str(part) for part in raw_values)
        elif operator == "between":
            raw_value = ",".join(str(part) for part in values)
        else:
            if value is not None:
                raw_value = str(value)
            elif values:
                raw_value = str(values[0])
            else:
                raw_value = ""
        if not column:
            raise ValueError(f"В фильтре не указана колонка: {item}")
        if operator not in {"is_null", "not_null"} and not raw_value:
            raise ValueError(f"Для фильтра {item!r} нужно передать value или values.")
        return column, operator, raw_value

    symbolic_match = re.fullmatch(r"\s*([A-Za-z_][\w.]*)\s*(==|=|!=|<>|>=|<=|>|<)\s*(.+)\s*", item)
    if symbolic_match is not None:
        column, operator, value = symbolic_match.groups()
        return column.strip(), normalize_filter_operator(operator), value.strip()

    parts = item.split(None, 2)
    if len(parts) < 2:
        raise ValueError(f"Некорректный фильтр: {item}")
    column = parts[0].strip()
    operator = normalize_filter_operator(parts[1])
    if operator not in _FILTER_OPERATORS:
        raise ValueError(f"Неподдерживаемый оператор фильтра: {operator}")
    value = parts[2].strip() if len(parts) > 2 else ""
    if operator not in {"is_null", "not_null"} and not value:
        raise ValueError(f"Для фильтра {item!r} нужно передать значение.")
    return column, operator, value


def _parse_filter_values(raw_value: str) -> list[str]:
    """Разбирает строку значений фильтра ``in`` или ``between``.

    Args:
        raw_value: Значения фильтра в формате ``a,b`` или ``a and b``.

    Returns:
        Список очищенных строковых значений.
    """

    text = str(raw_value).strip()
    if (text.startswith("(") and text.endswith(")")) or (text.startswith("[") and text.endswith("]")):
        text = text[1:-1].strip()
    if "," in text:
        parts = text.split(",")
    else:
        parts = re.split(r"\s+and\s+", text, maxsplit=1, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def _parse_derived_item(item: Any) -> tuple[str, str, str]:
    """Разбирает описание вычисляемой колонки.

    Args:
        item: Структурированное описание или строка вида ``new_col = operation(source_col)``.

    Returns:
        Кортеж ``(name, source_column, operation)``.
    """

    if not isinstance(item, str):
        name = str(_get_field(item, "name") or "").strip()
        source_column = str(_get_field(item, "source_column") or "").strip()
        operation = str(_get_field(item, "operation") or "").strip().lower()
        if not name or not source_column or operation not in _DERIVED_OPERATIONS:
            raise ValueError(f"Некорректное описание derived_columns: {item}")
        return name, source_column, operation

    match = re.fullmatch(r"\s*([A-Za-z_][\w]*)\s*=\s*([A-Za-z_][\w]*)\(([^)]+)\)\s*", item)
    if match is None:
        raise ValueError(f"Некорректное описание derived_columns: {item}")
    name, operation, source_column = match.groups()
    operation = operation.lower()
    if operation not in _DERIVED_OPERATIONS:
        raise ValueError(f"Неподдерживаемая операция derived_columns: {operation}")
    return name.strip(), source_column.strip(), operation


def _parse_aggregation_item(item: Any) -> tuple[str, str, str]:
    """Разбирает описание агрегата.

    Args:
        item: Структурированное описание или строка вида ``function(column) as alias``.

    Returns:
        Кортеж ``(function, column, alias)``.
    """

    if not isinstance(item, str):
        function = str(_get_field(item, "function") or "").strip().lower()
        column = str(_get_field(item, "column") or "").strip()
        alias = str(_get_field(item, "alias") or "").strip()
        if function not in _AGGREGATION_FUNCTIONS or not column:
            raise ValueError(f"Некорректное описание aggregations: {item}")
        return function, column, alias

    match = re.fullmatch(r"\s*([A-Za-z_][\w]*)\(([^)]+)\)(?:\s+as\s+([A-Za-z_][\w]*))?\s*", item, flags=re.I)
    if match is None:
        raise ValueError(f"Некорректное описание aggregations: {item}")
    function, column, alias = match.groups()
    function = function.lower()
    if function not in _AGGREGATION_FUNCTIONS:
        raise ValueError(f"Неподдерживаемая агрегатная функция: {function}")
    return function, column.strip(), (alias or "").strip()


def _parse_order_item(item: Any) -> tuple[str, str]:
    """Разбирает одно правило сортировки.

    Args:
        item: Структурированное правило или строка вида ``column asc``.

    Returns:
        Кортеж ``(column, direction)``.
    """

    if not isinstance(item, str):
        column = str(_get_field(item, "column") or "").strip()
        direction = str(_get_field(item, "direction") or "asc").strip().lower()
        if not column:
            raise ValueError(f"В сортировке не указана колонка: {item}")
        if direction not in {"asc", "desc"}:
            raise ValueError(f"Направление сортировки должно быть asc или desc: {item}")
        return column, direction

    parts = item.replace(":", " ").split()
    if not parts:
        raise ValueError("Пустое правило сортировки.")
    column = parts[0].strip()
    direction = parts[1].strip().lower() if len(parts) > 1 else "asc"
    if direction not in {"asc", "desc"}:
        raise ValueError(f"Направление сортировки должно быть asc или desc: {item}")
    return column, direction


def _parse_scalar(value: str) -> str | int | float | bool:
    """Приводит строковое значение фильтра к простому типу.

    Args:
        value: Строковое значение из фильтра.

    Returns:
        Строка, число или bool.
    """

    text = value.strip().strip("'\"")
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.fullmatch(r"-?\d+", text) and len(text.lstrip("-")) not in {8} and len(text.lstrip("-")) <= 15:
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _normalize_filter_scalar(column: str, value: Any) -> Any:
    """Нормализует значение фильтра с учётом формата колонки.

    Args:
        column: Имя колонки фильтра.
        value: Исходное значение из запроса.

    Returns:
        Для ``event_dt`` дата ISO ``YYYY-MM-DD`` преобразуется в ``YYYYMMDD``.
        Остальные значения возвращаются без изменений.
    """
    text = str(value).strip().strip("'\"")
    if column == "event_dt" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text.replace("-", "")
    return value


def _validate_columns(*, columns: list[str], available_columns: list[str], allow_empty: bool) -> str:
    """Проверяет наличие колонок в Spark DataFrame.

    Args:
        columns: Колонки, которые нужны запросу.
        available_columns: Колонки текущего Spark DataFrame.
        allow_empty: Можно ли передать пустой список.

    Returns:
        Пустая строка, если ошибок нет, иначе текст ошибки для агента.
    """

    normalized = [column for column in columns if column]
    if not normalized and not allow_empty:
        return _format_empty_select_error()
    forbidden = {column.lower() for column in normalized} & {"*", "all"}
    if forbidden:
        return (
            "Ошибка load_data: нельзя запрашивать все поля через '*' или 'all'.\n"
            "Исправление: в query укажи минимальный список колонок в SELECT.\n"
            "Пример: LOAD hits\\nPERIOD event_dt FROM '20260101' TO '20260131'\\n"
            "SELECT event_id, event_dt, event_time\\nWHERE event_id = '<event_id>'\\nLIMIT 1."
        )
    missing = sorted({column for column in normalized if column not in set(available_columns)})
    return _format_missing_columns(missing=missing, available_columns=available_columns) if missing else ""


def _format_empty_select_error() -> str:
    """Формирует точечную ошибку для вызова ``load_data`` без колонок результата.

    Args:
        Отсутствуют.

    Returns:
        Текст ошибки с шаблонами исправленного вызова.
    """

    return (
        "Ошибка load_data: обычная выборка без явного SELECT запрещена. "
        "Инструмент не выполняет SELECT *.\n"
        "Исправление для чтения строк: добавь в query SELECT с минимально нужными полями "
        "и, если есть ключ из задачи, добавь WHERE.\n"
        "Пример точечного поиска по event_id: LOAD hits\\n"
        "PERIOD event_dt FROM '20260101' TO '20260131'\\n"
        "SELECT event_id, event_dt, event_time\\nWHERE event_id = '<event_id>'\\nLIMIT 1.\n"
        "Исправление для расчёта: укажи агрегат прямо в SELECT, например "
        "SELECT event_description, count(event_id) AS events_count."
    )


def _format_missing_columns(*, missing: list[str], available_columns: list[str]) -> str:
    """Формирует текст ошибки по отсутствующим колонкам.

    Args:
        missing: Колонки, которых нет в DataFrame.
        available_columns: Доступные колонки DataFrame.

    Returns:
        Текст ошибки для повторного вызова инструмента.
    """

    return (
        "Ошибка load_data: в таблице нет колонок из запроса.\n"
        f"Отсутствующие поля: {', '.join(missing)}.\n"
        f"Доступные поля ({len(available_columns)}): {', '.join(available_columns)}.\n"
        "Исправление: перепиши query с существующими полями из списка выше или проверь нужный alias "
        "по skills; не повторяй тот же набор отсутствующих колонок."
    )


def _get_field(source: Any, key: str) -> Any:
    """Достаёт поле из dict или pydantic-модели.

    Args:
        source: Объект с данными фильтра, агрегации, вычисляемой колонки или сортировки.
        key: Имя поля.

    Returns:
        Значение поля или ``None``, если поле отсутствует.
    """

    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)
