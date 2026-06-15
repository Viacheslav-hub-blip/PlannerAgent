"""LangChain tool ``load_data`` для выполнения запросов через Spark.

Содержит функции:
- build_spark_data_tools: сборка LangChain tool;
- _read_table: выполнение подготовленного запроса;
- _resolve_table_name: разрешение alias источника;
- _available_table_aliases_text: форматирование списка alias;
- _apply_derived_columns: добавление вычисляемых колонок;
- _build_derived_column: построение Spark-выражения;
- _apply_filters: применение фильтров;
- _build_filter_expression: построение Spark-предиката;
- _apply_aggregations: применение агрегаций;
- _build_aggregation_expression: построение Spark-агрегата;
- _apply_order_by: сортировка результата.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from deep_agent.data.query_parser import _extract_query_args_with_llm
from deep_agent.data.query_values import (
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
from deep_agent.data.sources import TABLE_ALIASES
from deep_agent.data.query_schema import ReadTableInput
READ_TABLE_DESCRIPTION = (
    "load_data\n"
    "---\n"
    "Описание: универсальная безопасная выборка из доступных Spark-таблиц по короткому alias. "
    "Инструмент принимает один параметр query: SQL-подобный текст запроса. Агент пишет query по skills, "
    "а внутренний нормализатор преобразует его в структурированные аргументы и выполняет выборку. "
    "При успешной выборке возвращается pandas DataFrame с полным результатом запроса.\n\n"
    "Когда использовать:\n"
    "- нужно прочитать строки, события или агрегаты из таблиц hits, cards, uko, history_automarking "
    "или demo_client_timeline;\n"
    "- известны таблица, нужные колонки и фильтры по ключам/значениям;\n"
    "- известен точный event_id, но дата события ещё неизвестна: выполни точечный lookup без периода, "
    "получи event_dt и затем используй период в следующих выборках;\n"
    "- нужно проверить наличие записей, получить фактические поля события или посчитать агрегат "
    "по данным источника.\n\n"
    "Когда не использовать:\n"
    "- нет периода, даты начала или даты конца и нет точного фильтра event_id = <id>: "
    "сначала запроси недостающие данные;\n"
    "- нужно обработать уже выгруженный pickle/offload-файл: используй код поверх сохраненного результата, "
    "а не повторный load_data;\n"
    "- нужна произвольная Spark SQL-команда, join нескольких источников, запись данных, удаление данных "
    "или изменение таблиц;\n"
    "- требуется SELECT * / SELECT all: перечисли только нужные колонки.\n\n"
    "Параметры:\n"
    "- query (str, обяз.): SQL-подобный запрос. В query обязательно укажи LOAD/FROM с коротким alias, "
    "SELECT с явными колонками или агрегатами, при необходимости PERIOD, WHERE/GROUP BY/ORDER BY/LIMIT. "
    "Без PERIOD разрешён только точный WHERE event_id = '<id>'.\n\n"
    "Формат query:\n"
    "  LOAD <table_alias>\n"
    "  PERIOD <date_column> FROM '<YYYYMMDD>' TO '<YYYYMMDD>'\n"
    "  SELECT <column_1>, <column_2> [, COUNT(*) AS <alias>] [, count(<column>) AS <alias>]\n"
    "  WHERE <column> = '<value>' AND (<column> LIKE '%value%' OR <column> CONTAINS '<value>')\n"
    "  GROUP BY <column>\n"
    "  ORDER BY <column> ASC|DESC\n"
    "  LIMIT <int>\n\n"
    "Допустимые таблицы: hits, cards, uko, history_automarking, demo_client_timeline. "
    "Вместо LOAD можно использовать FROM, но имя источника должно быть коротким alias, а не Spark-путем, "
    "именем файла, workspace_file или pkl.\n\n"
    "Операторы WHERE:\n"
    "- равенство: =, ==, eq, equals -> внутренне нормализуется в eq;\n"
    "- не равно: !=, <>, ne, not_equals -> ne;\n"
    "- сравнения: >, >=, <, <=, gt, gte, lt, lte;\n"
    "- текстовый поиск: LIKE '%value%' или CONTAINS 'value' -> contains;\n"
    "- списки и интервалы: IN (...), BETWEEN <from> AND <to>;\n"
    "- несколько условий можно соединять через AND и OR.\n\n"
    "Ограничения:\n"
    "- период обязателен, кроме точечного поиска по exact event_id через оператор равенства;\n"
    "- SELECT * и SELECT all запрещены для обычной выборки, но COUNT(*) разрешен в агрегатах;\n"
    "- длинные идентификаторы передавай строками в кавычках, чтобы не потерять точность."
)


def build_spark_data_tools(spark: Any, query_parser_model: Any | None = None) -> list[BaseTool]:
    """Создает инструмент ``load_data`` поверх готовой Spark session.

    Args:
        spark: Активная ``pyspark.sql.SparkSession``, созданная один раз при старте приложения.
        query_parser_model: Chat-модель LangChain для внутреннего разбора SQL-подобного ``query``.

    Returns:
        Список с одним LangChain tool ``load_data``.
    """

    def read_table(query: str) -> Any:
        """Выполняет SQL-подобный запрос к Spark-таблице через переданную Spark session.

        Args:
            query: SQL-подобный запрос с alias таблицы и колонками результата.
                Период можно опустить только при точном фильтре по ``event_id``.

        Returns:
            pandas DataFrame с результатом или текст ошибки, который агент может исправить.
        """

        try:
            parsed = _extract_query_args_with_llm(query=query, query_parser_model=query_parser_model)
        except ValueError as exc:
            return f"Ошибка load_data: {exc}"

        result = _read_table(
            spark=spark,
            **parsed,
        )
        if hasattr(result, "attrs"):
            result.attrs["spark_query_code"] = query.strip()
            result.attrs["spark_is_aggregation"] = bool(parsed["aggregations"])
        return result

    return [
        StructuredTool.from_function(
            func=read_table,
            name="load_data",
            description=READ_TABLE_DESCRIPTION,
            args_schema=ReadTableInput,
        )
    ]



def _read_table(
    *,
    spark: Any,
    table_name: str,
    select_columns: Any,
    filters: Any,
    derived_columns: Any,
    group_by: Any,
    aggregations: Any,
    order_by: Any,
    max_rows: int | None,
) -> Any:
    """Выполняет Spark-запрос и возвращает pandas DataFrame.

    Args:
        spark: Активная Spark session.
        table_name: Имя таблицы Spark или view.
        select_columns: Поля результата списком.
        filters: Фильтры списком объектов.
        derived_columns: Вычисляемые колонки списком объектов.
        group_by: Поля группировки списком.
        aggregations: Агрегаты списком объектов.
        order_by: Сортировка списком объектов.
        max_rows: Максимальное число строк результата.

    Returns:
        pandas DataFrame с metadata в ``attrs`` или текст ошибки.
    """

    try:
        table_alias = table_name.strip()
        resolved_table_name = _resolve_table_name(table_alias)
        table = spark.table(resolved_table_name)
        total_rows = table.count()
        table = _apply_derived_columns(table=table, derived_columns=derived_columns)
        table = _apply_filters(table=table, filters=filters)
        matched_rows = table.count()

        group_columns = _parse_columns(group_by)
        aggregation_items = _split_items(aggregations)
        if aggregation_items:
            result = _apply_aggregations(table=table, group_columns=group_columns, aggregations=aggregation_items)
        else:
            columns = _parse_columns(select_columns)
            select_error = _validate_columns(columns=columns, available_columns=table.columns, allow_empty=False)
            if select_error:
                return select_error
            result = table.select(*columns)

        order_items = _split_items(order_by)
        if order_items:
            order_error = _validate_columns(
                columns=[_parse_order_item(item)[0] for item in order_items],
                available_columns=result.columns,
                allow_empty=True,
            )
            if order_error:
                return order_error
            result = _apply_order_by(table=result, order_by=order_items)

        if max_rows is not None:
            result = result.limit(max(0, int(max_rows)))

        frame = result.toPandas()
        frame.attrs["spark_table_name"] = table_alias
        frame.attrs["spark_resolved_table_name"] = resolved_table_name
        frame.attrs["spark_source_file"] = table_alias
        frame.attrs["spark_total_rows"] = int(total_rows)
        frame.attrs["spark_matched_rows"] = int(matched_rows)
        return frame
    except ValueError as exc:
        return f"Ошибка load_data: {exc}"


def _resolve_table_name(table_name: str) -> str:
    """Преобразует короткое имя таблицы в полное Spark-имя.

    Args:
        table_name: Короткий alias таблицы, который передала модель.

    Returns:
        Полное имя Spark-таблицы для ``spark.table``.

    Raises:
        ValueError: Передано неизвестное или похожее на файл значение ``table_name``.
    """

    normalized = table_name.strip()
    if not normalized:
        raise ValueError(f"нужно указать alias таблицы. Доступные таблицы: {_available_table_aliases_text()}.")
    suspicious_fragments = (".", "workspace_file", "select_columns=", "/", "\\", "=")
    if any(fragment in normalized for fragment in suspicious_fragments) or len(normalized) > 80:
        raise ValueError(
            "table_name должен быть коротким alias таблицы, а не путём к файлу, именем артефакта "
            f"или сгенерированным view. Доступные таблицы: {_available_table_aliases_text()}."
        )
    if normalized not in TABLE_ALIASES:
        raise ValueError(f"неизвестная таблица {normalized!r}. Доступные таблицы: {_available_table_aliases_text()}.")
    return TABLE_ALIASES[normalized]


def _available_table_aliases_text() -> str:
    """Возвращает человекочитаемый список alias таблиц для сообщений инструмента.

    Args:
        Отсутствуют.

    Returns:
        Строка с короткими именами таблиц через запятую.
    """

    return ", ".join(sorted(TABLE_ALIASES))


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


__all__ = [
    "READ_TABLE_DESCRIPTION",
    "TABLE_ALIASES",
    "build_spark_data_tools",
]
