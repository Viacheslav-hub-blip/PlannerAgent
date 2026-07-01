"""Построение и применение Spark-запросов для load_data.

Содержит функции:
- _resolve_table_name: проверка имени Spark-таблицы;
- _apply_derived_columns: добавление вычисляемых колонок;
- _build_derived_column: построение Spark-выражения;
- _apply_filters: применение фильтров;
- _build_filter_expression: построение Spark-предиката;
- _apply_aggregations: применение агрегаций;
- _build_aggregation_expression: построение Spark-агрегата;
- _apply_order_by: сортировка результата;
- _serialize_complex_columns_for_output: сериализация сложных Spark-типов для вывода;
- _build_pyspark_query_code: построение воспроизводимого PySpark-кода запроса;
- _format_pyspark_derived_expression: форматирование PySpark-выражения вычисляемой колонки;
- _format_pyspark_filter_expression: форматирование PySpark-предиката;
- _format_pyspark_aggregation_expression: форматирование PySpark-агрегата;
- _format_pyspark_order_expression: форматирование PySpark-сортировки;
- _pyspark_literal: форматирование Python-литерала для PySpark-кода;
- _strip_outer_quotes: удаление внешних кавычек из строкового значения фильтра.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deep_agent.data_processing.load_data_query_values import (
    _normalize_filter_scalar,
    _parse_aggregation_item,
    _parse_columns,
    _parse_derived_item,
    _parse_filter_item,
    _parse_filter_values,
    _parse_order_item,
    _parse_scalar,
    _split_items,
    _validate_columns,
)

def _resolve_table_name(table_name: str) -> str:
    """Проверяет имя таблицы и возвращает его для ``spark.table``.

    Args:
        table_name: Имя Spark-таблицы или view, которое передала модель.

    Returns:
        Имя Spark-таблицы для ``spark.table``.

    Raises:
        ValueError: Передано пустое или похожее на файл значение ``table_name``.
    """

    normalized = table_name.strip()
    if not normalized:
        raise ValueError("нужно указать имя Spark-таблицы или view.")
    suspicious_fragments = ("workspace_file", "select_columns=", "/", "\\", "=")
    if any(fragment in normalized for fragment in suspicious_fragments) or len(normalized) > 80:
        raise ValueError(
            "table_name должен быть именем Spark-таблицы или view, а не путём к файлу, "
            "именем артефакта или сериализованными аргументами запроса."
        )
    return normalized


def _apply_derived_columns(*, table: Any, derived_columns: Any) -> Any:
    """Добавляет вычисляемые колонки к Spark DataFrame.

    Args:
        table: Исходный Spark DataFrame.
        derived_columns: Описания вычисляемых колонок списком объектов или строкой.

    Returns:
        Spark DataFrame с добавленными колонками.
    """

    result = table
    for item in _split_items(derived_columns):
        name, source_column, operation = _parse_derived_item(item)
        missing = _validate_columns(columns=[source_column], available_columns=result.columns, allow_empty=False)
        if missing:
            raise ValueError(missing)
        result = result.withColumn(name, _build_derived_column(source_column=source_column, operation=operation))
    return result


def _build_derived_column(*, source_column: str, operation: str) -> Any:
    """Строит выражение Spark Column для вычисляемой колонки.

    Args:
        source_column: Исходная колонка.
        operation: Имя операции.

    Returns:
        Spark Column с вычисленным значением.
    """

    from pyspark.sql import functions as functions

    source = functions.col(source_column)
    if operation == "lower":
        return functions.lower(source.cast("string"))
    if operation == "upper":
        return functions.upper(source.cast("string"))
    if operation == "length":
        return functions.length(source.cast("string"))
    if operation == "abs":
        return functions.abs(source.cast("double"))

    digits = functions.regexp_replace(source.cast("string"), r"\D", "")
    if operation == "year":
        return digits.substr(1, 4)
    if operation == "month":
        return digits.substr(5, 2)
    if operation == "year_month":
        return digits.substr(1, 6)
    if operation == "date":
        return digits.substr(1, 8)
    raise ValueError(f"Неподдерживаемая операция вычисляемой колонки: {operation}")


def _apply_filters(*, table: Any, filters: Any) -> Any:
    """Применяет строковые фильтры к Spark DataFrame.

    Args:
        table: Исходный Spark DataFrame.
        filters: Фильтры списком объектов или одной строкой.

    Returns:
        Отфильтрованный Spark DataFrame.
    """

    result = table
    for item in _split_items(filters):
        column, _, _ = _parse_filter_item(item)
        missing = _validate_columns(columns=[column], available_columns=result.columns, allow_empty=False)
        if missing:
            raise ValueError(missing)
        result = result.filter(_build_filter_expression(item))
    return result


def _build_filter_expression(item: Any) -> Any:
    """Строит Spark Column-предикат из одного строкового фильтра.

    Args:
        item: Один фильтр в структурированном или строковом формате.

    Returns:
        Spark Column с булевым условием.
    """

    from pyspark.sql import functions as functions

    column, operator, raw_value = _parse_filter_item(item)
    spark_column = functions.col(column)
    if operator == "is_null":
        return spark_column.isNull()
    if operator == "not_null":
        return spark_column.isNotNull()
    if operator == "contains":
        return spark_column.cast("string").contains(raw_value)
    if operator == "contains_any":
        expression = None
        for value in _parse_filter_values(raw_value):
            item_expression = spark_column.cast("string").contains(value)
            expression = item_expression if expression is None else expression | item_expression
        if expression is None:
            raise ValueError("Для оператора contains_any нужно хотя бы одно значение.")
        return expression
    if operator == "in":
        return spark_column.isin(
            [
                _parse_scalar(_normalize_filter_scalar(column, value))
                for value in _parse_filter_values(raw_value)
            ]
        )
    if operator == "between":
        values = [
            _parse_scalar(_normalize_filter_scalar(column, value))
            for value in _parse_filter_values(raw_value)
        ]
        if len(values) != 2:
            raise ValueError("Для оператора between нужны два значения.")
        return spark_column.between(values[0], values[1])

    value = _parse_scalar(_normalize_filter_scalar(column, raw_value))
    if operator == "eq":
        return spark_column == value
    if operator == "ne":
        return spark_column != value
    if operator == "gt":
        return spark_column > value
    if operator == "gte":
        return spark_column >= value
    if operator == "lt":
        return spark_column < value
    if operator == "lte":
        return spark_column <= value
    raise ValueError(f"Неподдерживаемый оператор фильтра: {operator}")


def _apply_aggregations(*, table: Any, group_columns: list[str], aggregations: list[Any]) -> Any:
    """Применяет агрегаты к Spark DataFrame.

    Args:
        table: Отфильтрованный Spark DataFrame.
        group_columns: Поля группировки.
        aggregations: Описания агрегатов списком объектов или строк.

    Returns:
        Spark DataFrame с результатом агрегаций.
    """

    aggregation_columns = [
        column
        for item in aggregations
        for function, column, _alias in [_parse_aggregation_item(item)]
        if not (function == "count" and column == "*")
    ]
    missing = _validate_columns(
        columns=[*group_columns, *aggregation_columns],
        available_columns=table.columns,
        allow_empty=True,
    )
    if missing:
        raise ValueError(missing)

    expressions = [_build_aggregation_expression(item) for item in aggregations]
    if group_columns:
        return table.groupBy(*group_columns).agg(*expressions)
    return table.agg(*expressions)


def _build_aggregation_expression(item: Any) -> Any:
    """Строит Spark Column для одного агрегата.

    Args:
        item: Агрегат в структурированном или строковом формате.

    Returns:
        Spark Column с alias.
    """

    from pyspark.sql import functions as functions

    function, column, alias = _parse_aggregation_item(item)
    if function == "count":
        expression = functions.count("*") if column == "*" else functions.count(functions.col(column))
    elif function == "count_distinct":
        expression = functions.countDistinct(functions.col(column))
    elif function == "min":
        expression = functions.min(functions.col(column))
    elif function == "max":
        expression = functions.max(functions.col(column))
    elif function == "sum":
        expression = functions.sum(functions.col(column))
    elif function == "mean":
        expression = functions.avg(functions.col(column))
    else:
        raise ValueError(f"Неподдерживаемая агрегатная функция: {function}")
    return expression.alias(alias or f"{function}_{column}")


def _apply_order_by(*, table: Any, order_by: list[Any]) -> Any:
    """Сортирует Spark DataFrame.

    Args:
        table: Spark DataFrame результата.
        order_by: Правила сортировки списком объектов или строк.

    Returns:
        Отсортированный Spark DataFrame.
    """

    from pyspark.sql import functions as functions

    expressions = []
    for item in order_by:
        column, direction = _parse_order_item(item)
        expression = functions.col(column).asc() if direction == "asc" else functions.col(column).desc()
        expressions.append(expression)
    return table.orderBy(*expressions)


def _serialize_complex_columns_for_output(table: Any) -> Any:
    """Преобразует сложные Spark-колонки в JSON-строки перед выгрузкой результата.

    Args:
        table: Spark DataFrame после фильтров, выбора колонок, сортировки и лимита.

    Returns:
        Spark DataFrame с теми же именами колонок, где ``array``, ``map`` и ``struct``
        сериализованы через ``to_json`` для стабильной записи в JSONL и pandas preview.
    """

    from pyspark.sql import functions as functions
    from pyspark.sql.types import ArrayType, MapType, StructType

    expressions = []
    for field in table.schema.fields:
        column = functions.col(field.name)
        if isinstance(field.dataType, (ArrayType, MapType, StructType)):
            expressions.append(functions.to_json(column).alias(field.name))
        else:
            expressions.append(column)
    return table.select(*expressions)


def _build_pyspark_query_code(
    *,
    resolved_table_name: str,
    select_columns: Any,
    filters: Any,
    derived_columns: Any,
    group_by: Any,
    aggregations: Any,
    order_by: Any,
    max_rows: int | None,
    output_path: str | Path | None = None,
    final_output_path: str | Path | None = None,
) -> str:
    """Строит воспроизводимый PySpark-код фактической выборки.

    Args:
        resolved_table_name: Полное имя Spark-таблицы, переданное в ``spark.table``.
        select_columns: Поля результата списком или строкой.
        filters: Фильтры списком объектов или строкой.
        derived_columns: Вычисляемые колонки списком объектов или строкой.
        group_by: Поля группировки списком или строкой.
        aggregations: Агрегаты списком объектов или строкой.
        order_by: Сортировка списком объектов или строкой.
        max_rows: Максимальное число строк результата.
        output_path: Временная Spark output-папка для записи JSONL artifact; если ``None``,
            строится прежний код с ``toPandas()``.
        final_output_path: Финальный JSONL-файл после переноса Spark part-файла.

    Returns:
        Многострочный PySpark-код, эквивалентный выполненному запросу.
    """

    lines = [
        "from pyspark.sql import functions as F",
        "",
        f'df = spark.table({_pyspark_literal(resolved_table_name)})',
    ]
    for item in _split_items(derived_columns):
        name, source_column, operation = _parse_derived_item(item)
        expression = _format_pyspark_derived_expression(
            source_column=source_column,
            operation=operation,
        )
        lines.append(f'df = df.withColumn({_pyspark_literal(name)}, {expression})')
    for item in _split_items(filters):
        lines.append(f"df = df.filter({_format_pyspark_filter_expression(item)})")

    group_columns = _parse_columns(group_by)
    aggregation_items = _split_items(aggregations)
    if aggregation_items:
        aggregations_code = ", ".join(_format_pyspark_aggregation_expression(item) for item in aggregation_items)
        if group_columns:
            group_code = ", ".join(_pyspark_literal(column) for column in group_columns)
            lines.append(f"result = df.groupBy({group_code}).agg({aggregations_code})")
        else:
            lines.append(f"result = df.agg({aggregations_code})")
    else:
        columns = _parse_columns(select_columns)
        columns_code = ", ".join(_pyspark_literal(column) for column in columns)
        lines.append(f"result = df.select({columns_code})")

    for item in _split_items(order_by):
        lines.append(f"result = result.orderBy({_format_pyspark_order_expression(item)})")
    if max_rows is not None:
        lines.append(f"result = result.limit({max(0, int(max_rows))})")
    if output_path is None:
        lines.append("pdf = result.toPandas()")
    else:
        output_file = str(Path(final_output_path or output_path).resolve())
        lines.extend(
            [
                "from pathlib import Path",
                "",
                "row_count = result.count()",
                f"output_file = Path({_pyspark_literal(output_file)})",
                "output_file.parent.mkdir(parents=True, exist_ok=True)",
                "with output_file.open('w', encoding='utf-8') as file:",
                "    for row_json in result.toJSON().toLocalIterator():",
                "        file.write(row_json)",
                "        file.write('\\n')",
            ]
        )
        if final_output_path is not None:
            lines.extend(
                [
                    "# Spark отдает JSON-строки драйверу, а Python пишет итоговый JSONL локально.",
                ]
            )
    return "\n".join(lines)


def _format_pyspark_derived_expression(*, source_column: str, operation: str) -> str:
    """Форматирует PySpark-выражение вычисляемой колонки.

    Args:
        source_column: Исходная колонка.
        operation: Имя операции вычисления.

    Returns:
        Строка PySpark-кода для ``withColumn``.
    """

    column = f"F.col({_pyspark_literal(source_column)})"
    if operation == "lower":
        return f"F.lower({column}.cast('string'))"
    if operation == "upper":
        return f"F.upper({column}.cast('string'))"
    if operation == "length":
        return f"F.length({column}.cast('string'))"
    if operation == "abs":
        return f"F.abs({column}.cast('double'))"
    digits = f"F.regexp_replace({column}.cast('string'), r'\\D', '')"
    if operation == "year":
        return f"{digits}.substr(1, 4)"
    if operation == "month":
        return f"{digits}.substr(5, 2)"
    if operation == "year_month":
        return f"{digits}.substr(1, 6)"
    if operation == "date":
        return f"{digits}.substr(1, 8)"
    raise ValueError(f"Неподдерживаемая операция вычисляемой колонки: {operation}")


def _format_pyspark_filter_expression(item: Any) -> str:
    """Форматирует один фильтр в PySpark Column-предикат.

    Args:
        item: Фильтр в структурированном или строковом формате.

    Returns:
        Строка PySpark-кода для ``DataFrame.filter``.
    """

    column, operator, raw_value = _parse_filter_item(item)
    spark_column = f"F.col({_pyspark_literal(column)})"
    if operator == "is_null":
        return f"{spark_column}.isNull()"
    if operator == "not_null":
        return f"{spark_column}.isNotNull()"
    if operator == "contains":
        return f"{spark_column}.cast('string').contains({_pyspark_literal(_strip_outer_quotes(raw_value))})"
    if operator == "contains_any":
        parts = [
            f"{spark_column}.cast('string').contains({_pyspark_literal(_strip_outer_quotes(value))})"
            for value in _parse_filter_values(raw_value)
        ]
        return " | ".join(f"({part})" for part in parts)
    if operator == "in":
        values = [
            _parse_scalar(_normalize_filter_scalar(column, value))
            for value in _parse_filter_values(raw_value)
        ]
        values_code = ", ".join(_pyspark_literal(value) for value in values)
        return f"{spark_column}.isin([{values_code}])"
    if operator == "between":
        values = [
            _parse_scalar(_normalize_filter_scalar(column, value))
            for value in _parse_filter_values(raw_value)
        ]
        if len(values) != 2:
            raise ValueError("Для оператора between нужны два значения.")
        return f"{spark_column}.between({_pyspark_literal(values[0])}, {_pyspark_literal(values[1])})"

    value = _parse_scalar(_normalize_filter_scalar(column, raw_value))
    operator_map = {
        "eq": "==",
        "ne": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
    }
    if operator not in operator_map:
        raise ValueError(f"Неподдерживаемый оператор фильтра: {operator}")
    return f"{spark_column} {operator_map[operator]} {_pyspark_literal(value)}"


def _format_pyspark_aggregation_expression(item: Any) -> str:
    """Форматирует один агрегат в PySpark Column-выражение.

    Args:
        item: Агрегат в структурированном или строковом формате.

    Returns:
        Строка PySpark-кода для ``agg``.
    """

    function, column, alias = _parse_aggregation_item(item)
    if function == "count":
        expression = "F.count('*')" if column == "*" else f"F.count(F.col({_pyspark_literal(column)}))"
    elif function == "count_distinct":
        expression = f"F.countDistinct(F.col({_pyspark_literal(column)}))"
    elif function == "min":
        expression = f"F.min(F.col({_pyspark_literal(column)}))"
    elif function == "max":
        expression = f"F.max(F.col({_pyspark_literal(column)}))"
    elif function == "sum":
        expression = f"F.sum(F.col({_pyspark_literal(column)}))"
    elif function == "mean":
        expression = f"F.avg(F.col({_pyspark_literal(column)}))"
    else:
        raise ValueError(f"Неподдерживаемая агрегатная функция: {function}")
    return f"{expression}.alias({_pyspark_literal(alias or f'{function}_{column}')})"


def _format_pyspark_order_expression(item: Any) -> str:
    """Форматирует одно правило сортировки в PySpark Column-выражение.

    Args:
        item: Правило сортировки в структурированном или строковом формате.

    Returns:
        Строка PySpark-кода для ``orderBy``.
    """

    column, direction = _parse_order_item(item)
    method = "asc" if direction == "asc" else "desc"
    return f"F.col({_pyspark_literal(column)}).{method}()"


def _pyspark_literal(value: Any) -> str:
    """Форматирует Python-литерал для вставки в PySpark-код.

    Args:
        value: Значение аргумента PySpark-вызова.

    Returns:
        Строковое представление литерала Python.
    """

    return repr(value)


def _strip_outer_quotes(value: Any) -> str:
    """Удаляет внешние одинарные или двойные кавычки из значения фильтра.

    Args:
        value: Значение фильтра в строковом или произвольном формате.

    Returns:
        Строка без пары внешних кавычек.
    """

    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text

