"""Выполнение Spark action и сохранение результатов load_data.

Содержит функции:
- _write_result_to_jsonl: запись Spark DataFrame в один JSONL artifact;
- _write_result_rows_to_jsonl: запись Spark DataFrame через стандартный Spark writer;
- _build_hadoop_temp_output_path: построение временного Hadoop output-пути;
- _copy_hadoop_json_parts_to_local: копирование Spark part-файлов в локальный artifact;
- _delete_hadoop_path: удаление временной Hadoop-папки;
- _merge_spark_json_parts: объединение Spark part-файлов в один JSONL artifact;
- _read_jsonl_preview: чтение preview из готового JSONL artifact;
- _run_spark_action_with_progress: выполнение Spark action с progress-событиями;
- _clear_spark_job_group: очистка Spark job group с учётом разных версий PySpark;
- _cancel_spark_job_group: отмена Spark jobs по job group при ошибке;
- _cancel_all_spark_jobs: отмена активных Spark jobs перед stop;
- _emit_spark_status_progress: отправка progress по Spark stages/tasks;
- _emit_load_data_progress: отправка custom progress-события;
- _resolve_output_dir: нормализация каталога artifacts;
- _build_export_file_path: построение читаемого пути JSONL artifact;
- _artifact_value_fragment: преобразование части запроса в безопасный фрагмент имени;
- _workspace_artifact_path: построение workspace-пути artifact;
- _remove_path_inside_parent: безопасное удаление временного пути.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks.manager import dispatch_custom_event

from deep_agent.agent_settings import workspace_tool_path

LOAD_DATA_PROGRESS_EVENT = "load_data_progress"

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
        temp_output_dir: Служебный временный путь artifact, очищаемый перед локальной записью результата.
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
        action=lambda: _write_result_rows_to_jsonl(
            result=result,
            spark=spark,
            temp_output_dir=temp_output_dir,
            final_output_path=final_output_path,
        ),
    )
    _remove_path_inside_parent(temp_output_dir, final_output_path.parent)
    return final_output_path.resolve()


def _write_result_rows_to_jsonl(*, result: Any, spark: Any, temp_output_dir: Path, final_output_path: Path) -> None:
    """Записывает Spark DataFrame в JSONL-файл через стандартный Spark writer.

    Args:
        result: Spark DataFrame результата.
        spark: Активная Spark session с Hadoop configuration.
        temp_output_dir: Локальная временная папка для копии Spark ``part-*.json`` файлов.
        final_output_path: Итоговый ``.jsonl`` файл в каталоге artifacts.

    Returns:
        ``None``.
    """

    hadoop_output_path = _build_hadoop_temp_output_path(
        spark=spark,
        final_output_path=final_output_path,
    )
    try:
        result.write.mode("overwrite").json(hadoop_output_path)
        _copy_hadoop_json_parts_to_local(
            spark=spark,
            hadoop_output_path=hadoop_output_path,
            local_parts_dir=temp_output_dir,
        )
        _merge_spark_json_parts(temp_output_dir=temp_output_dir, final_output_path=final_output_path)
    finally:
        _delete_hadoop_path(spark=spark, hadoop_output_path=hadoop_output_path)


def _build_hadoop_temp_output_path(*, spark: Any, final_output_path: Path) -> str:
    """Строит временный Hadoop-путь в домашнем каталоге пользователя Spark.

    Args:
        spark: Активная Spark session.
        final_output_path: Итоговый локальный artifact-путь, из которого берется стабильный суффикс.

    Returns:
        Hadoop URI временной папки для ``DataFrameWriter``.
    """

    sc = spark.sparkContext
    jvm = sc._jvm
    configuration = sc._jsc.hadoopConfiguration()
    filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(configuration)
    home_dir = filesystem.getHomeDirectory().toString().rstrip("/")
    digest = hashlib.sha256(str(final_output_path.resolve()).encode("utf-8")).hexdigest()[:12]
    safe_stem = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in final_output_path.stem)
    return f"{home_dir}/.deepagent/load_data/{safe_stem}_{digest}.json_tmp"


def _copy_hadoop_json_parts_to_local(*, spark: Any, hadoop_output_path: str, local_parts_dir: Path) -> None:
    """Копирует Spark ``part-*.json`` из Hadoop output в локальную временную папку.

    Args:
        spark: Активная Spark session.
        hadoop_output_path: Hadoop-папка, созданная Spark writer.
        local_parts_dir: Локальная папка рядом с итоговым artifact.

    Returns:
        ``None``.

    Raises:
        ValueError: Spark writer не создал ни одного JSON part-файла.
    """

    _remove_path_inside_parent(local_parts_dir, local_parts_dir.parent)
    local_parts_dir.mkdir(parents=True, exist_ok=True)

    sc = spark.sparkContext
    jvm = sc._jvm
    configuration = sc._jsc.hadoopConfiguration()
    filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(configuration)
    output_path = jvm.org.apache.hadoop.fs.Path(hadoop_output_path)
    local_path_class = jvm.org.apache.hadoop.fs.Path

    copied = 0
    for status in filesystem.listStatus(output_path):
        source_path = status.getPath()
        file_name = source_path.getName()
        if not file_name.startswith("part-") or not file_name.endswith(".json"):
            continue
        target_path = local_parts_dir / file_name
        filesystem.copyToLocalFile(False, source_path, local_path_class(str(target_path)), True)
        copied += 1
    if copied == 0:
        raise ValueError(f"Spark writer не создал JSON part-файлы в {hadoop_output_path}.")


def _delete_hadoop_path(*, spark: Any, hadoop_output_path: str) -> None:
    """Удаляет временную Hadoop-папку после выгрузки.

    Args:
        spark: Активная Spark session.
        hadoop_output_path: Hadoop-путь для удаления.

    Returns:
        ``None``. Ошибки очистки не перекрывают основной результат.
    """

    try:
        sc = spark.sparkContext
        jvm = sc._jvm
        configuration = sc._jsc.hadoopConfiguration()
        filesystem = jvm.org.apache.hadoop.fs.FileSystem.get(configuration)
        filesystem.delete(jvm.org.apache.hadoop.fs.Path(hadoop_output_path), True)
    except Exception:
        return


def _merge_spark_json_parts(*, temp_output_dir: Path, final_output_path: Path) -> None:
    """Склеивает Spark ``part-*.json`` файлы в один локальный JSONL artifact.

    Args:
        temp_output_dir: Временная папка, которую создал Spark writer.
        final_output_path: Итоговый файл, доступный агенту как artifact.

    Returns:
        ``None``.
    """

    part_files = sorted(temp_output_dir.glob("part-*.json"))
    with final_output_path.open("w", encoding="utf-8") as file:
        for part_file in part_files:
            with part_file.open("r", encoding="utf-8") as part:
                shutil.copyfileobj(part, file)


def _read_jsonl_preview(*, file_path: Path, max_rows: int) -> list[dict[str, Any]]:
    """Читает первые строки JSONL artifact для preview без Spark action.

    Args:
        file_path: JSONL-файл, созданный ``load_data``.
        max_rows: Максимальное число строк preview.

    Returns:
        Список JSON-записей из начала файла.
    """

    rows: list[dict[str, Any]] = []
    if max_rows <= 0 or not file_path.exists():
        return rows
    with file_path.open("r", encoding="utf-8") as file:
        for line in file:
            if len(rows) >= max_rows:
                break
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            rows.append(value if isinstance(value, dict) else {"value": value})
    return rows


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
            _clear_spark_job_group(sc)

    _emit_load_data_progress(stage=stage, status="started", group_id=group_id)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_action)
        try:
            while not future.done():
                _emit_spark_status_progress(sc=sc, group_id=group_id, stage=stage)
                time.sleep(0.5)
            result = future.result()
        except BaseException as exc:
            _cancel_spark_job_group(sc=sc, group_id=group_id)
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


def _clear_spark_job_group(sc: Any) -> None:
    """Очищает текущую Spark job group с учётом разных версий PySpark.

    Args:
        sc: SparkContext, у которого может быть или отсутствовать метод ``clearJobGroup``.

    Returns:
        ``None``.
    """

    clear_job_group = getattr(sc, "clearJobGroup", None)
    if callable(clear_job_group):
        clear_job_group()
        return
    sc.setJobGroup("", "")


def _cancel_spark_job_group(*, sc: Any, group_id: str) -> None:
    """Отменяет Spark jobs текущего tool action по job group.

    Args:
        sc: SparkContext, управляющий текущими Spark jobs.
        group_id: Идентификатор Spark job group, которую нужно отменить.

    Returns:
        ``None``. Ошибки отмены не должны скрывать исходную ошибку Spark action.
    """

    cancel_job_group = getattr(sc, "cancelJobGroup", None)
    try:
        if callable(cancel_job_group):
            cancel_job_group(group_id)
        else:
            _cancel_all_spark_jobs(sc)
    except Exception:
        return


def _cancel_all_spark_jobs(sc: Any) -> None:
    """Отменяет все активные Spark jobs в SparkContext перед остановкой session.

    Args:
        sc: SparkContext, в котором могут оставаться активные jobs.

    Returns:
        ``None``. Ошибки отмены игнорируются, чтобы cleanup оставался best-effort.
    """

    cancel_all_jobs = getattr(sc, "cancelAllJobs", None)
    if callable(cancel_all_jobs):
        try:
            cancel_all_jobs()
        except Exception:
            return


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
    """Строит путь JSONL artifact из таблицы, фильтров и времени создания.

    Args:
        output_dir: Каталог артефактов.
        table_alias: Имя Spark-таблицы или view.
        select_columns: Поля результата; сохраняются в сигнатуре и не участвуют в имени.
        filters: Фильтры.
        derived_columns: Вычисляемые колонки; не участвуют в имени.
        group_by: Поля группировки; не участвуют в имени.
        aggregations: Агрегаты; не участвуют в имени.
        order_by: Сортировка; не участвует в имени.
        max_rows: Максимальное число строк; не участвует в имени.

    Returns:
        Путь с именем таблицы, фильтрами и временем создания.
    """

    del select_columns, derived_columns, group_by, aggregations, order_by, max_rows
    readable_parts = [_artifact_value_fragment(table_alias) or "table"]
    filters_fragment = _artifact_value_fragment(filters)
    if filters_fragment:
        readable_parts.append(f"where_{filters_fragment}")

    readable_query = "_".join(readable_parts)[:160].rstrip("_")
    created_at = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return (output_dir / f"load_data_{readable_query}_{created_at}.jsonl").resolve()


def _artifact_value_fragment(value: Any) -> str:
    """Преобразует значение части запроса в читаемый безопасный фрагмент имени.

    Args:
        value: Строка, число, Pydantic-модель, словарь или коллекция параметров запроса.

    Returns:
        Нормализованный фрагмент без пробелов и служебных символов.
    """

    if value is None:
        return ""
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True, exclude_defaults=True)
    if isinstance(value, dict):
        fragments = [_artifact_value_fragment(item) for item in value.values()]
        return "_".join(fragment for fragment in fragments if fragment)
    if isinstance(value, (list, tuple, set)):
        fragments = [_artifact_value_fragment(item) for item in value]
        return "_".join(fragment for fragment in fragments if fragment)

    normalized = re.sub(r"[^\w-]+", "_", str(value).casefold(), flags=re.UNICODE)
    return re.sub(r"_+", "_", normalized).strip("_")


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

