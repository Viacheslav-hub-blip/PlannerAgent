"""LangChain tool ``load_data`` для выполнения запросов через Spark.

Содержит функции:
- build_spark_data_tools: сборка LangChain tool;
- _read_table: выполнение подготовленного запроса;
- _request_spark_query_approval: запрос HITL-подтверждения перед Spark action;
- _write_result_to_jsonl: запись Spark DataFrame в один JSONL artifact;
- _run_spark_action_with_progress: выполнение Spark action с progress-событиями;
- _emit_load_data_progress: отправка custom progress-события;
- _clean_preview_value: приведение scalar preview к JSON-совместимому значению;
- _resolve_table_name: разрешение alias источника;
- _available_table_aliases_text: форматирование списка alias;
- _apply_derived_columns: добавление вычисляемых колонок;
- _build_derived_column: построение Spark-выражения;
- _apply_filters: применение фильтров;
- _build_filter_expression: построение Spark-предиката;
- _apply_aggregations: применение агрегаций;
- _build_aggregation_expression: построение Spark-агрегата;
- _apply_order_by: сортировка результата.
- _build_pyspark_query_code: построение воспроизводимого PySpark-кода запроса.
- _format_pyspark_derived_expression: форматирование PySpark-выражения вычисляемой колонки.
- _format_pyspark_filter_expression: форматирование PySpark-предиката.
- _format_pyspark_aggregation_expression: форматирование PySpark-агрегата.
- _format_pyspark_order_expression: форматирование PySpark-сортировки.
- _pyspark_literal: форматирование Python-литерала для PySpark-кода.
- _strip_outer_quotes: удаление внешних кавычек из строкового значения фильтра.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

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
from deep_agent.settings import workspace_tool_path

READ_TABLE_DESCRIPTION = (
    "load_data\n"
    "---\n"
    "Описание: универсальная безопасная выборка из доступных Spark-таблиц по короткому alias. "
    "Инструмент принимает один параметр query: SQL-подобный текст запроса. Агент пишет query по skills, "
    "а внутренний нормализатор преобразует его в структурированные аргументы и выполняет выборку. "
    "При успешной выборке материализует полный результат в JSONL-файл внутри /artifacts и возвращает путь, "
    "preview и метаданные. Перед выполнением Spark action пользователь должен подтвердить реальный PySpark-код.\n\n"
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
    "SELECT с явными колонками или агрегатами, при необходимости PERIOD, WHERE/GROUP BY/ORDER BY. "
    "LIMIT не является обязательным и разрешён только если пользователь явно попросил ограничить число строк, "
    "получить sample, top N, первые N или не более N строк. Не добавляй LIMIT самостоятельно для больших выгрузок: "
    "полный результат будет сохранён в artifact-файл, а в контекст попадёт только preview. "
    "Без PERIOD разрешён только точный WHERE event_id = '<id>'.\n\n"
    "Формат query:\n"
    "  LOAD <table_alias>\n"
    "  PERIOD <date_column> FROM '<YYYYMMDD>' TO '<YYYYMMDD>'\n"
    "  SELECT <column_1>, <column_2> [, COUNT(*) AS <alias>] [, count(<column>) AS <alias>]\n"
    "  WHERE <column> = '<value>' AND (<column> LIKE '%value%' OR <column> CONTAINS '<value>')\n"
    "  GROUP BY <column>\n"
    "  ORDER BY <column> ASC|DESC\n"
    "  LIMIT <int>  -- только при явном пользовательском ограничении строк\n\n"
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
    "- LIMIT запрещён, если пользователь явно не попросил ограничить число строк или получить sample/top N;\n"
    "- SELECT * и SELECT all запрещены для обычной выборки, но COUNT(*) разрешен в агрегатах;\n"
    "- длинные идентификаторы передавай строками в кавычках, чтобы не потерять точность."
)

DEFAULT_SPARK_OUTPUT_DIR = "artifacts"
DEFAULT_SPARK_PREVIEW_ROWS = 30
LOAD_DATA_PROGRESS_EVENT = "load_data_progress"


def build_spark_data_tools(
    spark: Any,
    query_parser_model: Any | None = None,
    *,
    output_dir: str | Path = DEFAULT_SPARK_OUTPUT_DIR,
    workspace_root: str | Path | None = None,
    preview_rows: int = DEFAULT_SPARK_PREVIEW_ROWS,
    require_approval: bool = True,
) -> list[BaseTool]:
    """Создает инструмент ``load_data`` поверх готовой Spark session.

    Args:
        spark: Активная ``pyspark.sql.SparkSession``, созданная один раз при старте приложения.
        query_parser_model: Chat-модель LangChain для внутреннего разбора SQL-подобного ``query``.
        output_dir: Каталог, куда ``load_data`` сохраняет JSONL artifact с полным результатом.
        workspace_root: Корень workspace для построения пути вида ``/artifacts/file.jsonl``.
            Если ``None``, используется текущая рабочая директория.
        preview_rows: Число строк preview, возвращаемых в контекст вместе с путем к artifact.
        require_approval: Нужно ли запрашивать HITL-подтверждение PySpark-кода перед Spark action.

    Returns:
        Список с одним LangChain tool ``load_data``.
    """

    resolved_workspace_root = Path(workspace_root or Path.cwd()).resolve()
    resolved_output_dir = _resolve_output_dir(output_dir=output_dir, workspace_root=resolved_workspace_root)

    def read_table(query: str) -> Any:
        """Выполняет SQL-подобный запрос к Spark-таблице через переданную Spark session.

        Args:
            query: SQL-подобный запрос с alias таблицы и колонками результата.
                Период можно опустить только при точном фильтре по ``event_id``.

        Returns:
            Словарь с artifact-путём, preview и метаданными или текст ошибки, который агент может исправить.
        """

        try:
            parsed = _extract_query_args_with_llm(query=query, query_parser_model=query_parser_model)
        except ValueError as exc:
            return f"Ошибка load_data: {exc}"

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


def _write_result_to_jsonl(
    *,
    spark: Any,
    result: Any,
    temp_output_dir: Path,
    final_output_path: Path,
    progress_group_id: str,
    progress_description: str,
) -> Path:
    """Сохраняет Spark DataFrame в один JSONL-файл без постоянной папки Spark output.

    Args:
        spark: Активная Spark session.
        result: Spark DataFrame результата.
        temp_output_dir: Временная папка Spark writer, удаляемая после переноса part-файла.
        final_output_path: Итоговый ``.jsonl`` файл в каталоге artifacts.
        progress_group_id: Spark job group для progress-событий записи.
        progress_description: Описание Spark job group для progress-событий.

    Returns:
        Абсолютный путь к итоговому JSONL-файлу.
    """

    _remove_path_inside_parent(temp_output_dir, final_output_path.parent)
    if final_output_path.exists():
        final_output_path.unlink()
    final_output_path.parent.mkdir(parents=True, exist_ok=True)

    _run_spark_action_with_progress(
        spark=spark,
        group_id=progress_group_id,
        description=progress_description,
        stage="write_jsonl",
        action=lambda: result.coalesce(1).write.mode("overwrite").json(str(temp_output_dir)),
    )
    part_files = sorted(temp_output_dir.glob("part-*.json"))
    if not part_files:
        _remove_path_inside_parent(temp_output_dir, final_output_path.parent)
        raise ValueError("Spark не создал JSON part-файл для результата load_data.")
    shutil.move(str(part_files[0]), str(final_output_path))
    _remove_path_inside_parent(temp_output_dir, final_output_path.parent)
    return final_output_path.resolve()


def _run_spark_action_with_progress(
    *,
    spark: Any,
    group_id: str,
    description: str,
    stage: str,
    action: Any,
) -> Any:
    """Выполняет Spark action и отправляет progress-события по stages/tasks.

    Args:
        spark: Активная Spark session.
        group_id: Уникальный Spark job group для отслеживания job/stage.
        description: Человекочитаемое описание Spark job group.
        stage: Логический этап ``load_data`` для UI.
        action: Функция без аргументов, запускающая Spark action.

    Returns:
        Результат ``action``.
    """

    sc = getattr(spark, "sparkContext", None)
    if sc is None:
        return action()

    def _run_action() -> Any:
        """Запускает action внутри job group и очищает group после завершения."""

        sc.setJobGroup(group_id, description, interruptOnCancel=True)
        try:
            return action()
        finally:
            sc.clearJobGroup()

    _emit_load_data_progress(stage=stage, status="started", group_id=group_id)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_action)
        try:
            while not future.done():
                _emit_spark_status_progress(sc=sc, group_id=group_id, stage=stage)
                time.sleep(0.5)
            result = future.result()
        except Exception as exc:
            _emit_load_data_progress(
                stage=stage,
                status="error",
                group_id=group_id,
                error=str(exc),
            )
            raise
    _emit_spark_status_progress(sc=sc, group_id=group_id, stage=stage)
    _emit_load_data_progress(stage=stage, status="completed", group_id=group_id)
    return result


def _emit_spark_status_progress(*, sc: Any, group_id: str, stage: str) -> None:
    """Считывает SparkStatusTracker и отправляет progress по stage/task.

    Args:
        sc: SparkContext.
        group_id: Spark job group, связанный с текущим ``load_data`` action.
        stage: Логический этап ``load_data``.

    Returns:
        ``None``.
    """

    try:
        tracker = sc.statusTracker()
        job_ids = list(tracker.getJobIdsForGroup(group_id))
    except Exception:
        return
    total_tasks = 0
    completed_tasks = 0
    active_tasks = 0
    failed_tasks = 0
    stage_ids: set[int] = set()
    for job_id in job_ids:
        job_info = tracker.getJobInfo(job_id)
        if job_info is None:
            continue
        for stage_id in list(getattr(job_info, "stageIds", []) or []):
            stage_ids.add(int(stage_id))
            stage_info = tracker.getStageInfo(stage_id)
            if stage_info is None:
                continue
            total_tasks += int(getattr(stage_info, "numTasks", 0) or 0)
            completed_tasks += int(getattr(stage_info, "numCompletedTasks", 0) or 0)
            active_tasks += int(getattr(stage_info, "numActiveTasks", 0) or 0)
            failed_tasks += int(getattr(stage_info, "numFailedTasks", 0) or 0)
    progress = None
    if total_tasks:
        progress = round(completed_tasks / total_tasks, 4)
    _emit_load_data_progress(
        stage=stage,
        status="running",
        group_id=group_id,
        job_ids=job_ids,
        stage_ids=sorted(stage_ids),
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        active_tasks=active_tasks,
        failed_tasks=failed_tasks,
        progress=progress,
    )


def _emit_load_data_progress(**payload: Any) -> None:
    """Отправляет custom event ``load_data_progress`` без падения основного Spark action.

    Args:
        **payload: Поля progress-события для UI или callback handler.

    Returns:
        ``None``.
    """

    try:
        event_payload = {"event": LOAD_DATA_PROGRESS_EVENT, **payload}
        dispatch_custom_event(LOAD_DATA_PROGRESS_EVENT, event_payload)
    except Exception:
        return


def _resolve_output_dir(*, output_dir: str | Path, workspace_root: Path) -> Path:
    """Преобразует каталог артефактов в абсолютный путь.

    Args:
        output_dir: Относительный или абсолютный каталог артефактов.
        workspace_root: Корень workspace для относительных путей.

    Returns:
        Абсолютный путь к каталогу артефактов.
    """

    path = Path(output_dir)
    return (path if path.is_absolute() else workspace_root / path).resolve()


def _build_export_file_path(
    *,
    output_dir: Path,
    table_alias: str,
    select_columns: Any,
    filters: Any,
    derived_columns: Any,
    group_by: Any,
    aggregations: Any,
    order_by: Any,
    max_rows: int | None,
) -> Path:
    """Строит стабильный путь JSONL artifact для конкретного Spark-запроса.

    Args:
        output_dir: Каталог артефактов.
        table_alias: Короткий alias таблицы.
        select_columns: Поля результата.
        filters: Фильтры.
        derived_columns: Вычисляемые колонки.
        group_by: Поля группировки.
        aggregations: Агрегаты.
        order_by: Сортировка.
        max_rows: Максимальное число строк.

    Returns:
        Путь вида ``<output_dir>/load_data_<table>_<hash>.jsonl``.
    """

    fingerprint = repr(
        (
            table_alias,
            select_columns,
            filters,
            derived_columns,
            group_by,
            aggregations,
            order_by,
            max_rows,
        )
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    safe_table = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in table_alias) or "table"
    return (output_dir / f"load_data_{safe_table}_{digest}.jsonl").resolve()


def _workspace_artifact_path(*, file_path: Path, workspace_root: Path) -> str:
    """Строит workspace-путь для сохраненного artifact.

    Args:
        file_path: Абсолютный путь к artifact-файлу.
        workspace_root: Корень workspace.

    Returns:
        POSIX workspace-путь или абсолютный путь, если файл вне workspace.
    """

    try:
        return workspace_tool_path(file_path.resolve(), workspace_root.resolve())
    except ValueError:
        return str(file_path.resolve())


def _remove_path_inside_parent(path: Path, parent: Path) -> None:
    """Удаляет файл или папку только если путь находится внутри ожидаемого родителя.

    Args:
        path: Удаляемый путь.
        parent: Разрешенный родительский каталог.

    Returns:
        ``None``.
    """

    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    try:
        resolved_path.relative_to(resolved_parent)
    except ValueError:
        raise ValueError(f"Небезопасный путь временного artifact вне каталога {resolved_parent}: {resolved_path}") from None
    if resolved_path.is_dir():
        shutil.rmtree(resolved_path)
    elif resolved_path.exists():
        resolved_path.unlink()


def _dataframe_to_records(frame: Any) -> list[dict[str, Any]]:
    """Преобразует pandas DataFrame preview в JSON-совместимые записи.

    Args:
        frame: pandas DataFrame, полученный через небольшой ``limit(...).toPandas()``.

    Returns:
        Список строк-словарей для preview.
    """

    records = frame.to_dict(orient="records")
    return [{str(key): _clean_preview_value(value) for key, value in record.items()} for record in records]


def _clean_preview_value(value: Any) -> Any:
    """Приводит значение preview к JSON-совместимому scalar.

    Args:
        value: Значение из pandas DataFrame preview.

    Returns:
        JSON-совместимое значение или строковое представление сложного scalar.
    """

    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


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
        lines.extend(
            [
                "row_count = result.count()",
                f"result.coalesce(1).write.mode('overwrite').json({_pyspark_literal(str(Path(output_path).resolve()))})",
            ]
        )
        if final_output_path is not None:
            lines.extend(
                [
                    "# Spark пишет JSONL как part-файл во временную папку.",
                    f"# После записи part-*.json переносится в {_pyspark_literal(str(Path(final_output_path).resolve()))}.",
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


__all__ = [
    "READ_TABLE_DESCRIPTION",
    "TABLE_ALIASES",
    "build_spark_data_tools",
]
