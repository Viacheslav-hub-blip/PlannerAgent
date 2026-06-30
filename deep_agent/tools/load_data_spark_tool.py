"""LangChain tool ``load_data`` для выполнения запросов через Spark.

Содержит функции:
- build_spark_data_tools: сборка LangChain tool;
- _managed_spark_session: жизненный цикл Spark session для одного tool call;
- _register_active_spark_session: регистрация Spark session для аварийной остановки;
- _unregister_active_spark_session: удаление Spark session из реестра аварийной остановки;
- _stop_spark_session: отмена jobs и остановка Spark session;
- stop_active_spark_sessions: аварийная остановка активных Spark session;
- _register_spark_shutdown_handlers: регистрация cleanup при завершении процесса;
- _spark_shutdown_signals: список сигналов для cleanup Spark session;
- _read_table: выполнение подготовленного запроса;
- _request_spark_query_approval: запрос HITL-подтверждения перед Spark action;
- build_load_data_approval_description: построение preview для HITL-подтверждения.
"""

from __future__ import annotations

import atexit
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

from deep_agent.data_processing.load_data_query_models import ReadTableInput
from deep_agent.data_processing.load_data_query_parser import _extract_query_args_with_llm
from deep_agent.data_processing.load_data_query_values import (
    _parse_columns,
    _parse_order_item,
    _split_items,
    _validate_columns,
)
from deep_agent.data_processing.load_data_spark_execution import (
    _build_export_file_path,
    _cancel_all_spark_jobs,
    _dataframe_to_records,
    _resolve_output_dir,
    _run_spark_action_with_progress,
    _workspace_artifact_path,
    _write_result_to_jsonl,
)
from deep_agent.data_processing.load_data_spark_query import (
    _apply_aggregations,
    _apply_derived_columns,
    _apply_filters,
    _apply_order_by,
    _build_pyspark_query_code,
    _resolve_table_name,
)

READ_TABLE_DESCRIPTION = (
    "load_data\n"
    "---\n"
    "Используй этот инструмент когда требуется сделать выгрузку из таблицы"
    "Инструмент принимает один параметр query: SQL-подобный текст запроса."
    "Когда использовать:\n"
    "- нужно прочитать строки, события или агрегаты из таблицы, которую указал пользователь или skill;\n"
    "- нужно проверить наличие записей, получить фактические поля события или посчитать агрегат "
    "по данным источника.\n\n"
    "Когда не использовать:\n"
    "- нужно обработать уже выгруженный pickle/offload-файл: используй код поверх сохраненного результата, "
    "а не повторный load_data;\n"
    "Параметры:\n"
    "- query (str, обяз.): SQL-подобный запрос. В query обязательно укажи LOAD/FROM с именем Spark-таблицы или view, "
    "SELECT с явными колонками или агрегатами, при необходимости PERIOD, WHERE/GROUP BY/ORDER BY. "
    "LIMIT не является обязательным и разрешён только если пользователь явно попросил ограничить число строк, "
    "получить sample, top N, первые N или не более N строк. Не добавляй LIMIT самостоятельно для больших выгрузок: "
    "полный результат будет сохранён в artifact-файл, а в контекст попадёт только preview. "
    "Формат query:\n"
    "  LOAD <table_name>\n"
    "  PERIOD <date_column> FROM '<YYYYMMDD>' TO '<YYYYMMDD>'\n"
    "  SELECT <column_1>, <column_2> [, COUNT(*) AS <alias>] [, count(<column>) AS <alias>]\n"
    "  WHERE <column> = '<value>' AND (<column> LIKE '%value%' OR <column> CONTAINS '<value>')\n"
    "  GROUP BY <column>\n"
    "  ORDER BY <column> ASC|DESC\n"
    "  LIMIT <int>  -- только при явном пользовательском ограничении строк\n\n"
    "Вместо LOAD можно использовать FROM, но имя источника должно быть Spark-таблицей или view, а не файловым путём, "
    "именем файла, workspace_file или pkl.\n\n"
    "Операторы WHERE:\n"
    "- равенство: =, ==, eq, equals -> внутренне нормализуется в eq;\n"
    "- не равно: !=, <>, ne, not_equals -> ne;\n"
    "- сравнения: >, >=, <, <=, gt, gte, lt, lte;\n"
    "- текстовый поиск: LIKE '%value%' или CONTAINS 'value' -> contains;\n"
    "- списки и интервалы: IN (...), BETWEEN <from> AND <to>;\n"
    "- несколько условий можно соединять через AND и OR.\n\n"
)

DEFAULT_SPARK_OUTPUT_DIR = "artifacts"
DEFAULT_SPARK_PREVIEW_ROWS = 30
_SPARK_TOOL_LOCK = threading.RLock()
_ACTIVE_SPARK_SESSIONS: dict[int, Any] = {}
_SPARK_SHUTDOWN_HANDLERS_REGISTERED = False


def build_spark_data_tools(
    spark_session_factory: Callable[[], Any],
    query_parser_model: Any | None = None,
    *,
    output_dir: str | Path = DEFAULT_SPARK_OUTPUT_DIR,
    workspace_root: str | Path | None = None,
    preview_rows: int = DEFAULT_SPARK_PREVIEW_ROWS,
    require_approval: bool = False,
) -> list[BaseTool]:
    """Создает инструмент ``load_data`` с новой Spark session на каждый вызов.

    Args:
        spark_session_factory: Функция без аргументов, создающая ``pyspark.sql.SparkSession`` для одного вызова.
        query_parser_model: Chat-модель LangChain для внутреннего разбора SQL-подобного ``query``.
        output_dir: Каталог, куда ``load_data`` сохраняет JSONL artifact с полным результатом.
        workspace_root: Корень workspace для построения пути вида ``/artifacts/file.jsonl``.
            Если ``None``, используется текущая рабочая директория.
        preview_rows: Число строк preview, возвращаемых в контекст вместе с путем к artifact.
        require_approval: Нужно ли запрашивать HITL-подтверждение PySpark-кода перед Spark action.

    Returns:
        Список с одним LangChain tool ``load_data``.
    """

    if not callable(spark_session_factory):
        raise TypeError("spark_session_factory должен быть callable, создающим SparkSession.")

    resolved_workspace_root = Path(workspace_root or Path.cwd()).resolve()
    resolved_output_dir = _resolve_output_dir(output_dir=output_dir, workspace_root=resolved_workspace_root)

    def read_table(query: str) -> Any:
        """Выполняет SQL-подобный запрос к Spark-таблице через отдельную Spark session.

        Args:
            query: SQL-подобный запрос с именем таблицы и колонками результата.
                Период можно опустить только при точном фильтре по ``event_id``.

        Returns:
            Словарь с artifact-путём, preview и метаданными или текст ошибки, который агент может исправить.
        """

        try:
            parsed = _extract_query_args_with_llm(query=query, query_parser_model=query_parser_model)
        except ValueError as exc:
            return f"Ошибка load_data: {exc}"

        with _managed_spark_session(spark_session_factory) as spark:
            result = _read_table(
                spark=spark,
                original_query=query,
                output_dir=resolved_output_dir,
                workspace_root=resolved_workspace_root,
                preview_rows=preview_rows,
                require_approval=require_approval,
                **parsed,
            )
        if isinstance(result, dict):
            result["original_query"] = query.strip()
            result["query_language"] = "pyspark"
            result["is_aggregation"] = bool(parsed["aggregations"])
        return result

    return [
        StructuredTool.from_function(
            func=read_table,
            name="load_data",
            description=READ_TABLE_DESCRIPTION,
            args_schema=ReadTableInput,
        )
    ]


@contextmanager
def _managed_spark_session(spark_session_factory: Callable[[], Any]) -> Iterator[Any]:
    """Создает Spark session для одного tool call и гарантирует остановку после него.

    Args:
        spark_session_factory: Функция без аргументов, возвращающая активную Spark session.

    Yields:
        Spark session, доступная только на время текущего вызова инструмента.

    Raises:
        ValueError: Фабрика вернула ``None`` вместо Spark session.
    """

    spark = None
    with _SPARK_TOOL_LOCK:
        try:
            spark = spark_session_factory()
            if spark is None:
                raise ValueError("spark_session_factory вернул None вместо SparkSession.")
            _register_active_spark_session(spark)
            yield spark
        finally:
            if spark is not None and id(spark) in _ACTIVE_SPARK_SESSIONS:
                try:
                    _stop_spark_session(spark)
                finally:
                    _unregister_active_spark_session(spark)


def _register_active_spark_session(spark: Any) -> None:
    """Добавляет Spark session в реестр аварийной остановки.

    Args:
        spark: Активная Spark session текущего вызова инструмента.

    Returns:
        ``None``.
    """

    _ACTIVE_SPARK_SESSIONS[id(spark)] = spark


def _unregister_active_spark_session(spark: Any) -> None:
    """Удаляет Spark session из реестра аварийной остановки.

    Args:
        spark: Spark session, которая уже остановлена или больше не принадлежит инструменту.

    Returns:
        ``None``.
    """

    _ACTIVE_SPARK_SESSIONS.pop(id(spark), None)


def _stop_spark_session(spark: Any) -> None:
    """Отменяет активные Spark jobs и останавливает Spark session.

    Args:
        spark: Spark session, которую нужно завершить без переиспользования.

    Returns:
        ``None``. Ошибки остановки не перекрывают основной результат инструмента.
    """

    sc = getattr(spark, "sparkContext", None)
    if sc is not None:
        _cancel_all_spark_jobs(sc)
    stop = getattr(spark, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:
            return


def stop_active_spark_sessions() -> None:
    """Останавливает все Spark session, зарегистрированные инструментом ``load_data``.

    Returns:
        ``None``. Функция используется для ``atexit`` и обработчиков завершения процесса.
    """

    with _SPARK_TOOL_LOCK:
        sessions = list(_ACTIVE_SPARK_SESSIONS.values())
        for spark in sessions:
            try:
                _stop_spark_session(spark)
            finally:
                _unregister_active_spark_session(spark)


def _register_spark_shutdown_handlers() -> None:
    """Регистрирует best-effort cleanup Spark session при завершении процесса.

    Returns:
        ``None``. Обработчики ставятся только в главном потоке и сохраняют прежнее поведение сигналов.
    """

    global _SPARK_SHUTDOWN_HANDLERS_REGISTERED
    if _SPARK_SHUTDOWN_HANDLERS_REGISTERED:
        return
    atexit.register(stop_active_spark_sessions)
    if threading.current_thread() is not threading.main_thread():
        _SPARK_SHUTDOWN_HANDLERS_REGISTERED = True
        return

    for signal_number in _spark_shutdown_signals():
        previous_handler = signal.getsignal(signal_number)

        def _handler(signum: int, frame: Any, previous: Any = previous_handler) -> None:
            """Останавливает Spark session и передает сигнал предыдущему обработчику.

            Args:
                signum: Номер полученного сигнала.
                frame: Текущий frame Python, переданный модулем ``signal``.
                previous: Обработчик, который был зарегистрирован до Spark cleanup.

            Returns:
                ``None``. Для стандартного обработчика завершает процесс через ``SystemExit``.
            """

            stop_active_spark_sessions()
            if callable(previous):
                previous(signum, frame)
                return
            if previous == signal.SIG_IGN:
                return
            raise SystemExit(128 + int(signum))

        try:
            signal.signal(signal_number, _handler)
        except (OSError, RuntimeError, ValueError):
            continue
    _SPARK_SHUTDOWN_HANDLERS_REGISTERED = True


def _spark_shutdown_signals() -> tuple[int, ...]:
    """Возвращает набор сигналов, при которых нужно завершать Spark session.

    Returns:
        Кортеж сигналов ``SIGINT``, ``SIGTERM`` и, на Windows, ``SIGBREAK``.
    """

    signals = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signals.append(sigbreak)
    return tuple(signals)


_register_spark_shutdown_handlers()


def _read_table(
    *,
    spark: Any,
    original_query: str = "",
    output_dir: Path | None = None,
    workspace_root: Path | None = None,
    preview_rows: int = DEFAULT_SPARK_PREVIEW_ROWS,
    require_approval: bool = True,
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
        original_query: Исходный SQL-подобный запрос, переданный в ``load_data``.
        output_dir: Каталог для сохранения JSONL artifact с полным результатом.
        workspace_root: Корень workspace для построения человекочитаемого artifact-пути.
        preview_rows: Число строк preview, возвращаемых в ответе инструмента.
        require_approval: Нужно ли останавливать граф на HITL-подтверждение PySpark-кода.
        table_name: Имя таблицы Spark или view.
        select_columns: Поля результата списком.
        filters: Фильтры списком объектов.
        derived_columns: Вычисляемые колонки списком объектов.
        group_by: Поля группировки списком.
        aggregations: Агрегаты списком объектов.
        order_by: Сортировка списком объектов.
        max_rows: Максимальное число строк результата.

    Returns:
        Словарь с metadata сохраненного JSONL artifact или текст ошибки.
    """

    try:
        resolved_output_dir = _resolve_output_dir(
            output_dir=output_dir or DEFAULT_SPARK_OUTPUT_DIR,
            workspace_root=workspace_root or Path.cwd(),
        )
        resolved_workspace_root = Path(workspace_root or Path.cwd()).resolve()
        table_alias = table_name.strip()
        resolved_table_name = _resolve_table_name(table_alias)
        export_path = _build_export_file_path(
            output_dir=resolved_output_dir,
            table_alias=table_alias,
            select_columns=select_columns,
            filters=filters,
            derived_columns=derived_columns,
            group_by=group_by,
            aggregations=aggregations,
            order_by=order_by,
            max_rows=max_rows,
        )
        temp_output_dir = export_path.with_suffix(export_path.suffix + ".tmp")
        query_code = _build_pyspark_query_code(
            resolved_table_name=resolved_table_name,
            select_columns=select_columns,
            filters=filters,
            derived_columns=derived_columns,
            group_by=group_by,
            aggregations=aggregations,
            order_by=order_by,
            max_rows=max_rows,
            output_path=temp_output_dir,
            final_output_path=export_path,
        )
        table = spark.table(resolved_table_name)
        table = _apply_derived_columns(table=table, derived_columns=derived_columns)
        table = _apply_filters(table=table, filters=filters)

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

        if require_approval:
            approval_result = _request_spark_query_approval(
                original_query=original_query,
                query_code=query_code,
                table_alias=table_alias,
                output_path=export_path,
            )
            if approval_result:
                return approval_result

        row_count = _run_spark_action_with_progress(
            spark=spark,
            group_id=f"load_data_count_{export_path.stem}",
            description=f"load_data count for {table_alias}",
            stage="count",
            action=lambda: int(result.count()),
        )
        _write_result_to_jsonl(
            spark=spark,
            result=result,
            temp_output_dir=temp_output_dir,
            final_output_path=export_path,
            progress_group_id=f"load_data_write_{export_path.stem}",
            progress_description=f"load_data write for {table_alias}",
        )
        preview_frame = _run_spark_action_with_progress(
            spark=spark,
            group_id=f"load_data_preview_{export_path.stem}",
            description=f"load_data preview for {table_alias}",
            stage="preview",
            action=lambda: result.limit(max(0, int(preview_rows))).toPandas(),
        )
        return {
            "artifact_type": "spark_load_data_file",
            "workspace_file": _workspace_artifact_path(
                file_path=export_path,
                workspace_root=resolved_workspace_root,
            ),
            "absolute_file": str(export_path.resolve()),
            "format": "jsonl",
            "rows": int(row_count),
            "columns": [str(column) for column in result.columns],
            "preview_rows": _dataframe_to_records(preview_frame),
            "table_name": table_alias,
            "resolved_table_name": resolved_table_name,
            "source_file": table_alias,
        }
    except ValueError as exc:
        return f"Ошибка load_data: {exc}"


def _request_spark_query_approval(
    *,
    original_query: str,
    query_code: str,
    table_alias: str,
    output_path: Path,
) -> str:
    """Запрашивает HITL-подтверждение перед выполнением Spark action.

    Args:
        original_query: SQL-подобный запрос пользователя или модели.
        query_code: Реальный PySpark-код, который будет выполнен после подтверждения.
        table_alias: Короткое имя источника данных.
        output_path: Финальный JSONL-файл, куда будет сохранён результат.

    Returns:
        Пустая строка при одобрении или текст отказа, если пользователь отклонил запрос.
    """

    response = interrupt(
        {
            "action_requests": [
                {
                    "name": "load_data",
                    "args": {"query": original_query},
                    "description": (
                        "Подтвердите выполнение Spark-запроса.\n\n"
                        f"Источник: {table_alias}\n"
                        f"Artifact: {output_path.resolve()}\n\n"
                        "Реальный PySpark-код с подставленными значениями:\n"
                        f"```python\n{query_code}\n```"
                    ),
                }
            ],
            "review_configs": [
                {
                    "action_name": "load_data",
                    "allowed_decisions": ["approve", "reject"],
                }
            ],
        }
    )
    decisions = response.get("decisions") if isinstance(response, dict) else None
    decision = decisions[0] if isinstance(decisions, list) and decisions else {}
    if not isinstance(decision, dict) or decision.get("type") == "approve":
        return ""
    message = decision.get("message") or "Пользователь отклонил выполнение Spark-запроса."
    return f"Запрос load_data отклонён до выполнения Spark action: {message}"


def build_load_data_approval_description(
    *,
    query: str,
    query_parser_model: Any | None,
    output_dir: str | Path = DEFAULT_SPARK_OUTPUT_DIR,
    workspace_root: str | Path | None = None,
) -> str:
    """Строит описание HITL-подтверждения ``load_data`` без выполнения Spark action.

    Args:
        query: SQL-подобный запрос из аргументов tool call ``load_data``.
        query_parser_model: Chat-модель для разбора ``query`` в структурированные аргументы.
        output_dir: Каталог будущего JSONL artifact.
        workspace_root: Корень workspace для абсолютного пути artifact.

    Returns:
        Текст approval request с исходным запросом, artifact path и реальным PySpark-кодом.
    """

    try:
        parsed = _extract_query_args_with_llm(query=query, query_parser_model=query_parser_model)
        resolved_workspace_root = Path(workspace_root or Path.cwd()).resolve()
        resolved_output_dir = _resolve_output_dir(
            output_dir=output_dir,
            workspace_root=resolved_workspace_root,
        )
        table_alias = str(parsed["table_name"]).strip()
        resolved_table_name = _resolve_table_name(table_alias)
        export_path = _build_export_file_path(
            output_dir=resolved_output_dir,
            table_alias=table_alias,
            select_columns=parsed["select_columns"],
            filters=parsed["filters"],
            derived_columns=parsed["derived_columns"],
            group_by=parsed["group_by"],
            aggregations=parsed["aggregations"],
            order_by=parsed["order_by"],
            max_rows=parsed["max_rows"],
        )
        temp_output_dir = export_path.with_suffix(export_path.suffix + ".tmp")
        query_code = _build_pyspark_query_code(
            resolved_table_name=resolved_table_name,
            select_columns=parsed["select_columns"],
            filters=parsed["filters"],
            derived_columns=parsed["derived_columns"],
            group_by=parsed["group_by"],
            aggregations=parsed["aggregations"],
            order_by=parsed["order_by"],
            max_rows=parsed["max_rows"],
            output_path=temp_output_dir,
            final_output_path=export_path,
        )
        return (
            "Подтвердите выполнение Spark-запроса.\n\n"
            f"Источник: {table_alias}\n"
            f"Artifact: {export_path.resolve()}\n\n"
            f"Исходный SQL-подобный запрос:\n{query.strip()}\n\n"
            "Реальный PySpark-код с подставленными значениями:\n"
            f"```python\n{query_code}\n```"
        )
    except Exception as exc:
        return (
            "Подтвердите выполнение `load_data`.\n\n"
            "Не удалось заранее построить PySpark preview для approval request.\n"
            f"Причина: {exc}\n\n"
            f"Аргумент query:\n{query.strip()}"
        )


__all__ = [
    "READ_TABLE_DESCRIPTION",
    "build_load_data_approval_description",
    "build_spark_data_tools",
    "stop_active_spark_sessions",
]

