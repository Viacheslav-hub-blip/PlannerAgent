"""Выполнение Spark action и сохранение результатов load_data.

Содержит функции:
- _write_result_to_jsonl: запись Spark DataFrame в один JSONL artifact;
- _write_result_rows_to_jsonl: потоковая запись строк Spark DataFrame в JSONL artifact;
- _run_spark_action_with_progress: выполнение Spark action с progress-событиями;
- _clear_spark_job_group: очистка Spark job group с учётом разных версий PySpark;
- _cancel_spark_job_group: отмена Spark jobs по job group при ошибке;
- _cancel_all_spark_jobs: отмена активных Spark jobs перед stop;
- _emit_spark_status_progress: отправка progress по Spark stages/tasks;
- _emit_load_data_progress: отправка custom progress-события;
- _resolve_output_dir: нормализация каталога artifacts;
- _build_export_file_path: построение стабильного пути JSONL artifact;
- _workspace_artifact_path: построение workspace-пути artifact;
- _remove_path_inside_parent: безопасное удаление временного пути;
- _dataframe_to_records: преобразование pandas preview в JSON-совместимые записи;
- _clean_preview_value: приведение scalar preview к JSON-совместимому значению.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
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
        action=lambda: _write_result_rows_to_jsonl(result=result, final_output_path=final_output_path),
    )
    _remove_path_inside_parent(temp_output_dir, final_output_path.parent)
    return final_output_path.resolve()


def _write_result_rows_to_jsonl(*, result: Any, final_output_path: Path) -> None:
    """Потоково записывает Spark DataFrame в локальный JSONL-файл.

    Args:
        result: Spark DataFrame результата.
        final_output_path: Итоговый ``.jsonl`` файл в каталоге artifacts.

    Returns:
        ``None``.
    """

    with final_output_path.open("w", encoding="utf-8") as file:
        for row_json in result.toJSON().toLocalIterator():
            file.write(row_json)
            file.write("\n")


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
    """Строит стабильный путь JSONL artifact для конкретного Spark-запроса.

    Args:
        output_dir: Каталог артефактов.
        table_alias: Имя Spark-таблицы или view.
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

